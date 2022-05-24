import os
import sys
import yaml
import runtime
import argparse
import pylab as pl
import numpy as np
import astropy.io.fits as fits

from   astropy.table    import Table, vstack
from   vmaxer           import vmaxer, vmaxer_rand
from   lumfn            import lumfn
from   lumfn_stepwise   import lumfn_stepwise
from   schechter        import schechter, named_schechter
from   renormalise_d8LF import renormalise_d8LF
from   delta8_limits    import d8_limits
from   config           import Configuration
from   findfile         import findfile, fetch_fields, overwrite_check, gather_cat, call_signature, write_desitable, fetch_header
from   jackknife_limits import solve_jackknife, set_jackknife, jackknife_mean
from   bitmask          import update_bit, lumfn_mask
from   params           import fillfactor_threshold


def process_cat(fpath, vmax_opath, field=None, survey='gama', extra_cols=[], bitmasks=['IN_D8LUMFN'], fillfactor=False, conservative=False, tier=None):        
    opath = vmax_opath

    if not os.path.isfile(fpath):
        # Do not crash and burn, but proceed on gracefully. 
        print('WARNING:  Failed to find {}'.format(fpath))
        return  1

    zmax  = Table.read(fpath)

    if len(zmax) == 0:
        print('Zero length catalogue, nothing to be done.') 
        return -99
             
    minz = zmax['ZSURV'].min()
    maxz = zmax['ZSURV'].max()
    
    print('Found redshift limits: {:.3f} < z < {:.3f}'.format(minz, maxz))

    update_bit(zmax['IN_D8LUMFN'], lumfn_mask, 'FILLFACTOR', zmax['FILLFACTOR'].data < fillfactor_threshold)

    vmax  = vmaxer(zmax, minz, maxz, fillfactor=fillfactor, bitmasks=bitmasks, extra_cols=extra_cols, tier=tier, field=field)
    vmax.meta['EXTNAME'] = 'VMAX'
        
    print('Writing {}.'.format(opath))

    write_desitable(opath, vmax)
    
    ##  Luminosity fn.
    opath  = opath.replace('vmax', 'lumfn')

    result = lumfn(vmax)
    result.meta['EXTNAME'] = 'LUMFN'

    write_desitable(opath, result)
    
    return  0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate Gold luminosity function.')
    parser.add_argument('--log', help='Create a log file of stdout.', action='store_true')
    parser.add_argument('--field', type=str, help='Select equatorial GAMA field: G9, G12, G15', default='G9')
    parser.add_argument('--survey', help='Select survey', default='gama')
    parser.add_argument('--density_split', help='Trigger density split luminosity function.', action='store_true')
    parser.add_argument('--dryrun', action='store_true', help='dryrun.')
    parser.add_argument('--nooverwrite',  help='Do not overwrite outputs if on disk', action='store_true')
    parser.add_argument('--selfcount_volfracs', help='Apply volfrac corrections based on randoms counting themselves as ddps.', action='store_true')
    parser.add_argument('--jackknife', help='Apply jack knife.', action='store_true')
    parser.add_argument('--conservative', help='Conservative analysis choices', action='store_true')
    
    args          = parser.parse_args()

    log           = args.log
    field         = args.field.upper()
    dryrun        = args.dryrun
    survey        = args.survey
    density_split = args.density_split
    self_count    = args.selfcount_volfracs
    jackknife     = args.jackknife
    conservative  = args.conservative
    
    if not density_split:
        if log:
            logfile = findfile(ftype='lumfn', dryrun=False, survey=survey, log=True)
            
            print(f'Logging to {logfile}')
                
            sys.stdout = open(logfile, 'w')

        print('Generating Gold reference LF.')

        call_signature(dryrun, sys.argv)

        # Bounded by gama gold, reference schechter limits:  
        # 0.039 < z < 0.263.
        # Note: not split by field. 
        
        fpath  = findfile(ftype='ddp_n8', dryrun=dryrun, survey=survey)
        opath  = findfile(ftype='vmax',   dryrun=dryrun, survey=survey)

        if args.nooverwrite:
            overwrite_check(opath)

        print(f'Reading: {fpath}')
        print(f'Writing: {opath}')

        process_cat(fpath, opath, survey=survey, fillfactor=True)

        if jackknife:
            vmax                           = Table.read(opath)
            rand_vmax                      = vmaxer_rand(survey=survey, ftype='randoms_bd_ddp_n8', dryrun=dryrun, prefix=prefix, conservative=conservative, write=False)

            # Solve for jack knife limits.
            njack, jk_volfrac, limits, jks = solve_jackknife(rand_vmax)

            rand_vmax['JK']                = jks
            rand_vmax.meta['NJACK']        = njack
            rand_vmax.meta['JK_VOLFRAC']   = jk_volfrac

            # Set jack knife limits to data.
            vmax['JK']                     = set_jackknife(vmax['RA'], vmax['DEC'], limits=limits, debug=False)
            vmax.meta['NJACK']             = njack
            vmax.meta['JK_VOLFRAC']        = jk_volfrac

            # Save jack knife limits.
            jpath                          = findfile(ftype='jackknife', prefix=prefix, dryrun=dryrun)

            with open(jpath, 'w') as ofile:
                yaml.dump(dict(limits), ofile, default_flow_style=False)

            print(f'Writing: {jpath}')

            lpath                          = findfile(ftype='lumfn', dryrun=dryrun, survey=survey, prefix=prefix)
            jackknife                      = np.arange(njack)

            lumfn(vmax, jackknife=jackknife, opath=lpath)

            print(f'Written {lpath}')

            jackknife_mean(lpath)
        
        print('Done.')

        if log:
            sys.stdout.close()

    else:
        if log:
            # HACK
            logfile = findfile(ftype='ddp_n8_d0_vmax', dryrun=False, field=field, survey=survey, log=True).replace('vmax', 'lumfn').replace('_{utier}', '')
                        
            print(f'Logging to {logfile}')
        
            sys.stdout = open(logfile, 'w')

        print('Generating Gold density-split LF.')

        call_signature(dryrun, sys.argv)

        assert  field != None        

        if dryrun:
            # A few galaxies have a high probability to be in highest density only. 
            utiers = np.array([8])

        else:
            utiers = np.arange(len(d8_limits))
                    
        rand_vmax_all   = None 

        for idx in utiers:
            print(f'\n\n\n\n----------------  Solving for density tier {idx}  ----------------\n\n')

            # Bounded by DDP1 z limits. 
            ddp_fpath   = findfile(ftype='ddp_n8_d0', dryrun=dryrun, field=field, survey=survey, utier=idx)
            ddp_opath   = findfile(ftype='ddp_n8_d0_vmax', dryrun=dryrun, field=field, survey=survey, utier=idx)
    
            print()
            print('Reading: {}'.format(ddp_fpath))

            '''
            try:
                failure = process_cat(ddp_fpath, ddp_opath, field=field, extra_cols=['MCOLOR_0P0', 'FIELD'], fillfactor=True, tier=idx)

            except Exception as E:
                print('Error: Failed gen_gold_lf --density_split on d0 tier {:d} with Exception:'.format(idx))
                print(E)
                print('skipping.')
                
                continue 
            '''

            failure = process_cat(ddp_fpath, ddp_opath, field=field, extra_cols=['MCOLOR_0P0', 'FIELD'], fillfactor=True, tier=idx) 

            print('LF process cat. complete.')

            if failure == -99:
                # Zero length (dryrun) catalog, nothing to be done.
                continue

            lpath                          = findfile(ftype='ddp_n8_d0_lumfn', field=field, dryrun=dryrun, survey=survey, utier=idx)
            result                         = Table.read(lpath)

            prefix                         = 'randoms_ddp1'
            rpath                          = findfile(ftype='randoms_bd_ddp_n8', dryrun=dryrun, field=field, survey=survey, prefix=prefix)

            ##  Used for multi-field avg. of d8 lfs. 
            fdelta_field                   = fetch_header(fpath=rpath, name='DDP1_d{}_VOLFRAC'.format(idx))

            if rand_vmax_all == None:
                print('Calculating multi-field volume fractions.')

                rand_vmax_all              = vmaxer_rand(survey=survey, ftype='randoms_bd_ddp_n8', dryrun=dryrun, prefix=prefix, conservative=conservative, write=True)            

            fdelta                         = float(rand_vmax_all.meta['DDP1_d{}_VOLFRAC'.format(idx)])
            fdelta_zp                      = float(rand_vmax_all.meta['DDP1_d{}_ZEROPOINT_VOLFRAC'.format(idx)])

            d8                             = float(rand_vmax_all.meta['DDP1_d{}_TIERMEDd8'.format(idx)])
            d8_zp                          = float(rand_vmax_all.meta['DDP1_d{}_ZEROPOINT_TIERMEDd8'.format(idx)])

            rand_vmax                      = rand_vmax_all[rand_vmax_all['DDP1_DELTA8_TIER'] == idx]
        
            if jackknife:
                print('Solving for jack knife limits.')
            
                njack, jk_volfrac, limits, jks = solve_jackknife(rand_vmax)
                
                rand_vmax['JK']                = jks
                rand_vmax.meta['NJACK']        = njack
                rand_vmax.meta['JK_VOLFRAC']   = jk_volfrac

                print('Setting data jack knife limits.')
            
                vmax_path                      = findfile(ftype='ddp_n8_d0_vmax', dryrun=dryrun, field=field, utier=idx, survey=survey)
                vmax                           = Table.read(vmax_path, format='fits')
            
                vmax['JK']                     = set_jackknife(vmax['RA'], vmax['DEC'], limits=limits, debug=False)
                vmax.meta['NJACK']             = njack
                vmax.meta['JK_VOLFRAC']        = jk_volfrac

                for ii in np.arange(1,2,1):
                    # Fraction of DDP1 volume meeting completeness cut.   
                    vmax.meta['DDP1_FULL8FRAC'] = rand_vmax_all.meta['DDP1_FULL8FRAC']

                print('Writing jack knife limits yaml')

                jpath                          = findfile(ftype='jackknife', prefix=prefix, dryrun=dryrun)
            
                with open(jpath, 'w') as jfile:
                    yaml.dump(dict(limits), jfile, default_flow_style=False)

                    jackknife                      = np.arange(njack)

                print('Solving for jacked up luminosity functions.')

                lumfn(vmax, jackknife=jackknife, opath=lpath)

                print('Solving for jacked up luminosity function mean.')
            
                jackknife_mean(lpath)

                # Reload result with JK columns.
                result = Table.read(lpath)

                with fits.open(lpath, mode='update') as hdulist:
                    assert  hdulist[1].header['EXTNAME'] == 'LUMFN'

                    hdulist[1] = result_hdu

                    for i, hdu in enumerate(hdulist):
                        hdr     = hdu.header

                        if 'EXTNAME' not in hdu.header:
                            continue

                        if 'JK' in hdu.header['EXTNAME']:
                            extname    = hdu.header['EXTNAME']

                            print(f'Updating {extname}')

                            result_jk  = Table(hdu.data, names=hdu.data.names)
                            result_jk  = renormalise_d8LF(idx, result_jk, fdelta, fdelta_zp, self_count)
                            result_jk  = fits.BinTableHDU(result_jk, name=extname, header=hdr)

                            hdulist[i] = result_jk

                        hdulist.append(ref_result_hdu)
                    
                    hdulist.flush()
                    hdulist.close()
            '''
            print('Renormalising LUMFN.')

            if self_count & (fdelta > 0.0) & (fdelta_zp > 0.0):
                result = renormalise_d8LF(idx, result, fdelta, fdelta_zp, self_count)
            
            else:
                assert dryrun, 'ERROR:  lf renormalisation has failed.'
            '''
            print('Solving for reference Schechter.')

            result['REF_SCHECHTER']  = named_schechter(result['MEDIAN_M'], named_type='TMR')
            result['REF_SCHECHTER'] *= (1. + d8) / (1. + 0.007)

            result['REF_RATIO']      = result['PHI_IVMAX'] / result['REF_SCHECHTER']

            # Update lumfn.fits with volfracs etc.                                                                                                                                                         
            result.meta['DDP1_d{}_VOLFRAC'.format(idx)]             = '{:.6f}'.format(fdelta)
            result.meta['DDP1_d{}_TIERMEDd8'.format(idx)]           = '{:.6f}'.format(d8)
            result.meta['DDP1_d{}_ZEROPOINT_VOLFRAC'.format(idx)]   = '{:.6f}'.format(fdelta_zp)
            result.meta['DDP1_d{}_ZEROPOINT_TIERMEDd8'.format(idx)] = '{:.6f}'.format(d8_zp)
            result.meta['DDP1_d{}_VOLFRAC_FIELD'.format(idx)]       = fdelta_field

            print('LF renormalization and ref. schechter complete.')
            
            result.pprint()

            # Reference Schechter - finer binning
            sch_Ms     = np.arange(-23., -15., 1.e-3)

            sch        = named_schechter(sch_Ms, named_type='TMR')
            sch       *= (1. + d8) / (1. + 0.007)

            ##
            ref_result = Table(np.c_[sch_Ms, sch], names=['MS', 'REFSCHECHTER'])            
            ref_result.meta['DDP1_d{}_VOLFRAC'.format(idx)]             = '{:.6f}'.format(fdelta)
            ref_result.meta['DDP1_d{}_TIERMEDd8'.format(idx)]           = '{:.6f}'.format(d8)
            ref_result.meta['DDP1_d{}_ZEROPOINT_VOLFRAC'.format(idx)]   = '{:.6f}'.format(fdelta_zp)
            ref_result.meta['DDP1_d{}_ZEROPOINT_TIERMEDd8'.format(idx)] = '{:.6f}'.format(d8_zp)
            
            keys            = sorted(result.meta.keys())
            header          = {}

            print('Creating header:')
            
            for key in keys:
                header[key] = str(result.meta[key])

                print(key, header[key])

            primary_hdu     = fits.PrimaryHDU()
            hdr             = fits.Header(header)
            result_hdu      = fits.BinTableHDU(result, name='LUMFN', header=hdr)
            ref_result_hdu  = fits.BinTableHDU(ref_result, name='REFERENCE')
            
            hdul            = fits.HDUList([primary_hdu, result_hdu, ref_result_hdu])

            print('Writing {}'.format(lpath))

            hdul.writeto(lpath, overwrite=True, checksum=True)
            
        print('Done.')

        if log:
            sys.stdout.close()

