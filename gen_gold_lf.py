import os
import sys
import runtime
import argparse
import pylab as pl
import numpy as np
import astropy.io.fits as fits
import matplotlib.pyplot as plt

from   astropy.table    import Table, vstack
from   vmaxer           import vmaxer
from   smith_kcorr      import test_plots, test_nonnative_plots
from   cosmo            import distmod, volcom
from   lumfn            import lumfn
from   schechter        import schechter, named_schechter
from   renormalise_d8LF import renormalise_d8LF
from   delta8_limits    import d8_limits
from   config           import Configuration

from   findfile         import findfile, fetch_fields, overwrite_check, gather_cat

def process_cat(fpath, vmax_opath, field=None, survey='gama', rand_paths=[], extra_cols=[], fillfactor=False, conservative=False):
    assert 'vmax' in vmax_opath

    opath = vmax_opath

    if not os.path.isfile(fpath):
        print('WARNING:  Failed to find {}'.format(fpath))
        return  1

    zmax = Table.read(fpath)
 
    # print(fpath)
    
    if 'FIELD' not in zmax.dtype.names:
        # HACK
        if 'ROS' in zmax.dtype.names:
            zmax['FIELD'] = zmax['ROS']

        else:
            raise  RuntimeError('FIELD MISSING FROM DTYPES.')
        
    found_fields = np.unique(zmax['FIELD'].data)
        
    print('Found fields: {}'.format(found_fields))

    zsurv = f'Z{survey}'.upper()
    
    minz = zmax[zsurv].min()
    maxz = zmax[zsurv].max()
    
    print('Found redshift limits: {:.3f} < z < {:.3f}'.format(minz, maxz))

    if field != None:
        assert  len(found_fields) == 1, 'ERROR: EXPECTED SINGLE FIELD RESTRICTED INPUT, e.g. G9.'

    rand  = gather_cat(rand_paths)

    vmax  = vmaxer(zmax, minz, maxz, extra_cols=extra_cols, rand=rand, zcol='Z{}'.format(survey.upper()), conservative=conservative)

    print('WARNING:  Found {:.3f}% with zmax < 0.0'.format(100. * np.mean(vmax['ZMAX'] <= 0.0)))
    
    # TODO: Why do we need this?                                                                                                   
    vmax = vmax[vmax['ZMAX'] >= 0.0]
    
    print('Writing {}.'.format(opath))

    vmax.write(opath, format='fits', overwrite=True)
    
    ##  Luminosity fn.
    opath  = opath.replace('vmax', 'lumfn')
    result = lumfn(vmax, fillfactor=fillfactor)

    print('Writing {}.'.format(opath))
    
    result.write(opath, format='fits', overwrite=True)

    return  0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate Gold luminosity function.')
    parser.add_argument('-f', '--field', type=str, help='Select equatorial GAMA field: G9, G12, G15', required=False, default=None)
    parser.add_argument('-s', '--survey', help='Select survey', default='gama')
    parser.add_argument('-d', '--density_split', help='Trigger density split luminosity function.', action='store_true')
    parser.add_argument('--dryrun', action='store_true', help='dryrun.')
    parser.add_argument('--prefix', help='filename prefix', default='randoms')
    parser.add_argument('--nooverwrite',  help='Do not overwrite outputs if on disk', action='store_true')
    parser.add_argument('--selfcount_volfracs', help='Apply volfrac corrections based on randoms counting themselves as ddps.', action='store_true')
    
    args   = parser.parse_args()

    field  = args.field
    dryrun = args.dryrun
    survey = args.survey
    density_split = args.density_split
    prefix = args.prefix
    self_count = args.selfcount_volfracs
    
    if density_split:
        assert  field != None
        assert  'ddp1' in prefix

    if not density_split:
        print('Generating Gold reference LF.')

        # Bounded by gama gold, reference schechter limits:  
        # 0.039 < z < 0.263.
        # Note: not split by field. 
        
        fpath = findfile(ftype='ddp',  dryrun=dryrun, survey=survey, prefix=prefix)
        opath = findfile(ftype='vmax', dryrun=dryrun, survey=survey, prefix=prefix)

        if args.nooverwrite:
            overwrite_check(opath)

        print(f'Reading: {fpath}')
        print(f'Writing: {opath}')

        process_cat(fpath, opath, rand_paths=[], survey=survey, fillfactor=False)

    else:
        print('Generating Gold density-split LF.')

        field = field.upper()

        rpath = findfile(ftype='randoms_bd_ddp_n8', dryrun=dryrun, field=field, survey=survey, prefix=prefix)
        
        if dryrun:
            # A few galaxies have a high probability to be in highest density only. 
            utiers = np.array([8])

        else:
            utiers = np.arange(len(d8_limits))
                    
        all_rands = None 

        for idx in utiers:
            ddp_idx   = idx + 1

            # Bounded by DDP1 z limits. 
            ddp_fpath = findfile(ftype='ddp_n8_d0', dryrun=dryrun, field=field, survey=survey, utier=idx, prefix=prefix)
            ddp_opath = findfile(ftype='ddp_n8_d0_vmax', dryrun=dryrun, field=field, survey=survey, utier=idx, prefix=prefix)
    
            print()
            print('Reading: {}'.format(ddp_fpath))
            
            failure = process_cat(ddp_fpath, ddp_opath, field=field, rand_paths=[rpath], extra_cols=['MCOLOR_0P0', 'FIELD'], fillfactor=True)

            if failure:
                print('FAILED on d0 tier {:d}; skipping.'.format(idx))
                continue
        
            print('LF process cat. complete.')
                    
            result = Table.read(ddp_opath.replace('vmax', 'lumfn'))        

            # result.pprint()

            if all_rands == None:                                
                _fields = fetch_fields(survey=survey)
                
                all_rpaths = [findfile(ftype='randoms_bd_ddp_n8', dryrun=dryrun, field=ff, survey=survey, prefix=prefix) for ff in _fields]
                all_rands = [Table.read(xx) for xx in all_rpaths]
 
            # Calculated for DDP1 redshift limits. 
    
            fdelta = np.array([float(x.meta['DDP1_d{}_VOLFRAC'.format(idx)]) for x in all_rands])
            d8     = np.array([float(x.meta['DDP1_d{}_TIERMEDd8'.format(idx)]) for x in all_rands])
            
            fdelta_zeropoint = np.array([float(x.meta['DDP1_d{}_ZEROPOINT_VOLFRAC'.format(idx)]) for x in all_rands])
            d8_zeropoint     = np.array([float(x.meta['DDP1_d{}_ZEROPOINT_TIERMEDd8'.format(idx)]) for x in all_rands])
            
            print('Field vol renormalization: {}'.format(fdelta))
            print('Field d8  renormalization: {}'.format(d8))

            fdelta = fdelta.mean()
            d8     = d8.mean()

            fdelta_zeropoint = fdelta_zeropoint.mean()
            d8_zeropoint     = d8_zeropoint.mean()
            
            print('Found mean vol. renormalisation scale of {:.3f}'.format(fdelta))
            print('Found mean  d8  renormalisation scale of {:.3f}'.format(d8))

            result = renormalise_d8LF(result, fdelta, fdelta_zeropoint, self_count)
            
            result['REF_SCHECHTER']  = named_schechter(result['MEDIAN_M'], named_type='TMR')
            result['REF_SCHECHTER'] *= (1. + d8) / (1. + 0.007)

            print('LF renormalization and ref. schechter complete.')
            
            result.pprint()

            # 
            sch_Ms = np.arange(-23., -15., 1.e-3)

            sch    = named_schechter(sch_Ms, named_type='TMR')
            sch   *= (1. + d8) / (1. + 0.007)

            ##
            ref_result = Table(np.c_[sch_Ms, sch], names=['MS', 'd{}_REFSCHECHTER'.format(idx)])            
            ref_result.meta['DDP1_d{}_VOLFRAC'.format(idx)]   = '{:.6e}'.format(fdelta)
            ref_result.meta['DDP1_d{}_TIERMEDd8'.format(idx)] = '{:.6e}'.format(d8)
            ref_result.meta['DDP1_d{}_ZEROPOINT_VOLFRAC'.format(idx)]   = '{:.6e}'.format(fdelta_zeropoint)
            ref_result.meta['DDP1_d{}_ZEROPOINT_TIERMEDd8'.format(idx)] = '{:.6e}'.format(d8_zeropoint)
            
            print('Writing {}'.format(ddp_opath.replace('vmax', 'lumfn')))

            primary_hdu    = fits.PrimaryHDU()

            keys           = sorted(result.meta.keys())
            
            header         = {}
            
            for key in keys:
                header[key] = str(result.meta[key])

            hdr            = fits.Header(header)
            result_hdu     = fits.BinTableHDU(result, name='LUMFN', header=hdr)
            ref_result_hdu = fits.BinTableHDU(ref_result, name='REFERENCE')
            hdul           = fits.HDUList([primary_hdu, result_hdu, ref_result_hdu])

            hdul.writeto(ddp_opath.replace('vmax', 'lumfn'), overwrite=True, checksum=True)

    print('Done.')
