import os
import time
import glob
import datetime
import fitsio
import subprocess
import numpy as np
import astropy.io.fits as   fits

from   collections     import OrderedDict
from   astropy.table   import Table, vstack
from   delta8_limits   import d8_limits
from   gama_fields     import gama_fields
from   desi_fields     import desi_fields
from   astropy.io.fits import getval, getheader

from   gama_fields   import gama_fields
from   desi_fields   import desi_fields

supported = ['gold',\
             'kE',\
             'zmax',\
             'vmax',\
             'lumfn',\
             'lumfn_step',\
             'ddp',\
             'ddp_n8']


def reset():
    from bin.pipeline import run_command
    
    fpaths= file_check(return_success=False, immutable=True)
    
    for fpath in fpaths:
        cmd = f'rm -rf {fpath}'
        out = run_command(cmd, noid=True)


def call_signature(dryrun, argv):
    if dryrun:
        print('\n\nCall signature:  python3 ' + ' '.join(argv) + '\n\n')

def gather_cat(fpaths):
    if len(fpaths) == 0:
        return  None

    assert  np.all(np.array([os.path.isfile(x) for x in fpaths]))

    tables      = [Table.read(x) for x in fpaths]
    tables      = vstack(tables)

    # TODO:  Headers, e.g. Area, ngal etc.  
    tables.meta = {}

    return  tables 

def write_desitable(opath, table, test=False):
    if test:
        table      = Table()
        table['a'] = [1, 4]
        table['b'] = [2.0, 5.0]
        table['c'] = ['x', 'y']

        opath      = './test.fits'

    # HACK TODO: FIX
    #assert table != None
    assert 'fits' in opath

    table.write(opath, format='fits', overwrite=True)

    cmds   = []
    cmds.append(f'chgrp desi {opath}')
    cmds.append(f'chmod  770 {opath}')
    
    for cmd in cmds:
        output = subprocess.check_output(cmd, shell=True)
        
        print(cmd, output)

def fetch_fields(survey):
    if survey == 'gama':
        fields = gama_fields   

    elif survey == 'desi':
        fields = desi_fields

    else:
        raise NotImplementedError

    return fields

def release_dir(user=os.environ['USER'], survey='gama', version=None):
    # E.g.  /cosma/home/durham/dc-wils7/data/GAMA4/                                                                                                                                                
    if version == 'latest':
        ff = glob.glob('/cosma/home/durham/{}/data/v*'.format(user))
        ff.sort(key=os.path.getmtime)

        return  ff[-1]
    
    elif version != None:
        return '/cosma/home/durham/{}/data/{}/'.format(user, version)

    else:
        return '/cosma/home/durham/{}/data/GAMA4/'.format(user)

def overwrite_check(opath, ext=None):
    if os.path.isfile(opath):
        exist     = True

        if ext != None:
            hdul  = fits.open(opath)
            exist = False

            # print(ext)
            # print(hdul.info())

            for hdu in hdul:
                hdr = hdu.header

                try:
                    if hdr['EXTNAME'] == 'BOUNDARY':
                        exist = True

                        print(f'WARNING:  Found existing BOUNDARY extension to {opath} and overwrite forbidden (--nooverwrite).')
                        
                except KeyError as E:
                    pass

        else:
            print(f'{opath} found on disk and overwrite forbidden (--nooverwrite).')

        if exist:
            exit(0)
        

def fetch_header(ftype=None, name=None, ext=1, allsupported=False, dryrun=False, prefix=None, field=None, utier='{utier}', survey=None, realz=0, debug=False, version=None, fpath=None):
    if allsupported:
        result  = OrderedDict()

        defined = []

        for ss in supported:
            additions  = fetch_header(ftype=ss, name=name, ext=ext, dryrun=dryrun, prefix=prefix, field=field, utier=utier, survey=survey, realz=realz, debug=debug, version=version)

            for xx in defined:
                additions.pop(xx, None)

            if additions:
                defined += list(additions.keys())

                result[ss] = additions

        return  result

    if fpath is None:
        fpath = findfile(ftype=ftype, dryrun=dryrun, prefix=prefix, field=field, utier=utier, survey=survey, realz=realz, debug=debug, version=version)
 
    if name:
        return  getval(fpath, name, ext)

    else:
        hdr   = getheader(fpath, ext)
        cards = [card for card in hdr.cards if np.all(~np.isin(card[0][:5], ["TUNIT", "TNULL", "TTYPE", "TFORM", "XTENS", "NAXIS", "BITPI", "PCOUN", "GCOUN"]))]
        
        result = {}

        for card in cards:
            try:
                result[card[0]] = card[1]

            except Exception as E:
                print(f'WARNING: {E}')

        return  result

def findfile(ftype, dryrun=False, prefix=None, field=None, utier='{utier}', survey=None, realz=0, debug=False, version=None, oversample=1):        
    if survey == None:
        survey = 'gama'

        print('WARNING: defaulting to survey=gama')
    
    survey = survey.lower()
    
    # Special case:                                                                                                                                                                                 
    if (ftype == 'gold') & dryrun & (survey == 'gama'):
        return  os.environ['CODE_ROOT'] + '/data/gama_gold_dryrun.fits'

    fields = fetch_fields(survey)
    
    if field != None:
        assert field in fields, print(f'Requested field {field} is not available in fields {fields}')
    
    if dryrun:
        dryrun = '_dryrun'
        debug  = True

    else:
        dryrun = ''
        
    if realz >= 50:
        raise ValueError('Randoms realizations limisted to max. of 50')

    if version == None:        
        if 'GOLD_DIR' in os.environ:
            gold_dir = os.environ['GOLD_DIR']

        else:
            gold_dir = os.environ['HOME'] + '/data/GAMA4/'

            print('Warning:  GOLD_DIR not defined in environment; assuming {gold_dir}')
            
        if 'RANDOMS_DIR' in os.environ:
            rand_dir = os.environ['RANDOMS_DIR']

        else:
            rand_dir = os.environ['HOME'] + '/data/GAMA4/randoms/'

            print('Warning:  RANDOMS_DIR not defined in environment; assuming {randoms_dir}')
        
    else:
        gold_dir = release_dir(version=version)
        rand_dir = release_dir(version=version) + '/randoms/'
        
    if isinstance(field, list):
        return  [findfile(ftype, dryrun=dryrun, prefix=prefix, field=ff, utier=utier) for ff in field]

    if ftype == 'summary_log':
        return  gold_dir + 'summary.log'
        
    if field == None:
        file_types = {'gold':       {'dir': gold_dir, 'id': f'{survey}',      'ftype': 'gold'},\
                      'kE':         {'dir': gold_dir, 'id': f'{survey}_gold', 'ftype': 'kE'},\
                      'zmax':       {'dir': gold_dir, 'id': f'{survey}_gold', 'ftype': 'zmax'},\
                      'vmax':       {'dir': gold_dir, 'id': f'{survey}_gold', 'ftype': 'vmax'},\
                      'lumfn':      {'dir': gold_dir, 'id': f'{survey}_gold', 'ftype': 'lumfn'},\
                      'lumfn_step': {'dir': gold_dir, 'id': f'{survey}_gold', 'ftype': 'lumfn_step'},\
                      'ddp':        {'dir': gold_dir, 'id': f'{survey}_gold', 'ftype': 'ddp'},\
                      'ddp_n8':     {'dir': gold_dir, 'id': f'{survey}_gold', 'ftype': 'ddp_n8'}}

        parts      = file_types[ftype]
        fpath      = parts['dir'] + '/{}_{}{}.fits'.format(parts['id'], parts['ftype'], dryrun)

    else: 
        file_types = {'ddp_n8_d0':          {'dir': gold_dir, 'id': f'{survey}_gold',         'ftype': 'ddp_n8_d0_{}'.format(utier)},\
                      'ddp_n8_d0_vmax':     {'dir': gold_dir, 'id': f'{survey}_gold',         'ftype': 'ddp_n8_d0_{}_vmax'.format(utier)},\
                      'ddp_n8_d0_lumfn':    {'dir': gold_dir, 'id': f'{survey}_gold',         'ftype': 'ddp_n8_d0_{}_lumfn'.format(utier)},\
                      'randoms':            {'dir': rand_dir, 'id': 'randoms',                'ftype': realz},\
                      'randoms_n8':         {'dir': rand_dir, 'id': 'randoms_N8',             'ftype': realz},\
                      'randoms_bd':         {'dir': rand_dir, 'id': 'randoms_bd',             'ftype': realz},\
                      'randoms_bd_ddp_n8':  {'dir': rand_dir, 'id': 'randoms_bd_ddp_n8',      'ftype': realz}
                     }
        
        parts      = file_types[ftype]

        if oversample > 1:
            oversample = f'_x{oversample}'
        else:
            oversample = ''
            
        fpath      = f'' + parts['dir'] + '/{}_{}{}_{}{}.fits'.format(parts['id'], field, oversample, parts['ftype'], dryrun)

            
    if prefix != None:
        assert 'randoms' in prefix;
        
        # HACK TODO: Fix
        #assert 'randoms' in fpath

        dirname = os.path.dirname(fpath)
        fpath   = os.path.basename(fpath)
            
        fpath   = fpath.replace('randoms', prefix)
        fpath   = dirname + '/' + fpath
        
    if debug:
        print(f'DEBUG: findfile returns {fpath}')

    fpath = fpath.replace('//', '/')
        
    return  fpath

def supported_files(dryrun=None):        
    try:
        dryrun = os.environ['DRYRUN']

    except Exception as E:
        print(E)

        dryrun = ''

    fpaths = []

    for survey in ['desi', 'gama']:
        for xx in supported:
            fpaths.append(findfile(xx, dryrun=False, survey=survey))

        fields = fetch_fields(survey)

        for field in fields:
            for prefix in [None, 'randoms_ddp1']:
                fpaths.append(findfile('randoms',            dryrun=False, field=field, prefix=prefix, survey=survey))
                fpaths.append(findfile('randoms_n8',         dryrun=False, field=field, prefix=prefix, survey=survey))
                fpaths.append(findfile('randoms_bd',         dryrun=False, field=field, prefix=prefix, survey=survey))
                fpaths.append(findfile('randoms_bd_ddp_n8',  dryrun=False, field=field, prefix=prefix, survey=survey))

            for ii, _ in enumerate(d8_limits):
                fpaths.append(findfile('ddp_n8_d0',       dryrun=False, field=field, utier=ii, survey=survey))
                fpaths.append(findfile('ddp_n8_d0_vmax',  dryrun=False, field=field, utier=ii, survey=survey))
                fpaths.append(findfile('ddp_n8_d0_lumfn', dryrun=False, field=field, utier=ii, survey=survey))

    return fpaths

def unsupported_files(dryrun=None):
    fpaths = supported_files(dryrun=dryrun)

    gold_paths  = sorted(glob.glob(os.environ['GOLD_DIR']    + '/*.fits'))
    rand_paths  = sorted(glob.glob(os.environ['RANDOMS_DIR'] + '/*.fits'))

    all_paths   = gold_paths + rand_paths

    unsupported = [x for x in all_paths if x not in fpaths]
    unsupported = [x for x in unsupported if 'dryrun' not in x]

    return unsupported

def file_check(dryrun=None):
    fpaths = supported_files(dryrun=dryrun)
    unsupported = unsupported_files(dryrun=dryrun)

    print('\n\n----  SUPPORTED FPATHS    ----\n')

    for fp in fpaths:
        if os.path.isfile(fp):
            mtime = os.path.getmtime(fp)
            mtime = datetime.datetime.utcfromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

            try:
                immutable = fetch_header(fpath=fp, name='IMMUTABLE')
            
            except:
                immutable = 'UNDEFINED'

        else:
            mtime = ''

        print('{}\t\t{}\t{}\t{}'.format(fp.ljust(100), os.path.isfile(fp), mtime, immutable))
    
    print('\n\n----  UNSUPPORTED FPATHS    ----\n')
    
    for fp in unsupported:
        if os.path.isfile(fp):
            mtime = os.path.getmtime(fp)
            mtime = datetime.datetime.utcfromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            
            try:
                immutable =fetch_header(fpath=fp, name='IMMUTABLE')
                
            except:
                immutable = 'UNDEFINED'

        else:
            mtime = ''

        print('{}\t\t{}\t{}\t{}'.format(fp.ljust(100), os.path.isfile(fp), mtime, immutable))
=======

    if return_success == True:
        print('\n\n----  SUPPORTED FPATHS    ----\n')

        for fp in fpaths:
            if os.path.isfile(fp):
                mtime = os.path.getmtime(fp)
                mtime = datetime.datetime.utcfromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

            else:
                mtime = ''

            print('{}\t\t{}\t{}'.format(fp.ljust(100), os.path.isfile(fp), mtime))

        
    if not immutable:
        gold_paths  = sorted(glob.glob(os.environ['GOLD_DIR']    + '/*.fits'))
        rand_paths  = sorted(glob.glob(os.environ['RANDOMS_DIR'] + '/*.fits'))
        all_paths   = gold_paths + rand_paths

    else:
        gama_gold_paths  = sorted(glob.glob(os.environ['GOLD_DIR']    + '/gama*.fits'))
        desi_gold_paths  = sorted(glob.glob(os.environ['GOLD_DIR']    + '/desi_gold_*.fits'))
        rand_paths  = sorted(glob.glob(os.environ['RANDOMS_DIR'] + '/gama*.fits'))
        all_paths   = gama_gold_paths + desi_gold_paths + rand_paths
        
    if return_success == False:
        return all_paths

    unsupported = [x for x in all_paths if x not in fpaths]
    unsupported = [x for x in unsupported if 'dryrun' not in x]

    
    if return_success == True:
        print('\n\n----  UNSUPPORTED FPATHS    ----\n')

        for fp in unsupported:
            if os.path.isfile(fp):
                mtime = os.path.getmtime(fp)
                mtime = datetime.datetime.utcfromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            else:
                mtime = ''

            print('{}\t\t{}\t{}'.format(fp.ljust(100), os.path.isfile(fp), mtime))
>>>>>>> 3055d01ba7082f79cf470ed1441a7611a80ea520

    return  ~np.all([os.path.isfile(fp) for fp in fpaths])


if __name__ == '__main__':
    failure = file_check()
    
    print('\n\nSuccess: {}\n\n'.format(~failure))
