import os
import gc
import time
import tqdm
import fitsio
import numpy             as np
import matplotlib.pyplot as plt
import argparse

from   astropy.table     import Table
from   scipy.spatial     import KDTree
from   cartesian         import cartesian
from   delta8_limits     import d8_limits, delta8_tier
from   runtime           import calc_runtime
from   findfile          import fetch_fields, findfile, overwrite_check
from   config            import Configuration
from   volfracs          import volfracs

'''
def volfracs(rand, bitmasks=[]):
    utiers    = np.unique(rand['DDP1_DELTA8_TIER'].data)
    utiers_zp = np.unique(rand['DDP1_DELTA8_TIER_ZEROPOINT'].data)

    print('Unique tiers: {}'.format(utiers))

    ddp1_rand = rand[rand['DDPZLIMS'][:,0]]

    for ut in utiers:
        in_tier = (ddp1_rand['DDP1_DELTA8_TIER'].data == ut)

        for bm in bitmasks:
            # Deprecated: (ddp1_rand['FILLFACTOR'].data >= 0.8)   
            in_tier &= (ddp1_rand[bm].data == 0)

        rand.meta['DDP1_d{}_VOLFRAC'.format(ut)]   = '{:.6e}'.format(np.mean(in_tier))
        rand.meta['DDP1_d{}_TIERMEDd8'.format(ut)] = '{:.6e}'.format(np.median(ddp1_rand['DDP1_DELTA8'].data[in_tier]))

        print('DDP1_d{}_VOLFRAC OF {:.4f} added.'.format(ut, np.mean(in_tier)))
        print('DDP1_d{}_TIERMED d8 OF {} added.'.format(ut, rand.meta['DDP1_d{}_TIERMEDd8'.format(ut)]))

        # Zero point.                                                                                                                                                                                    
        in_tier = (ddp1_rand['DDP1_DELTA8_TIER_ZEROPOINT'].data == ut) & (ddp1_rand['FILLFACTOR'].data >= 0.8)

        rand.meta['DDP1_d{}_ZEROPOINT_VOLFRAC'.format(ut)]   = '{:.6e}'.format(np.mean(in_tier))
        rand.meta['DDP1_d{}_ZEROPOINT_TIERMEDd8'.format(ut)] = '{:.6e}'.format(np.median(ddp1_rand['DDP1_DELTA8_ZEROPOINT'].data[in_tier]))
        
        print('DDP1_d{}_ZEROPOINT_VOLFRAC OF {:.4f} added.'.format(ut, np.mean(in_tier)))
        print('DDP1_d{}_ZEROPOINT_TIERMED d8 OF {} added.'.format(ut, rand.meta['DDP1_d{}_ZEROPOINT_TIERMEDd8'.format(ut)]))

    return rand
'''
parser  = argparse.ArgumentParser(description='Calculate DDP1 N8 for all randoms.')
parser.add_argument('-f', '--field', type=str, help='Select equatorial GAMA field: G9, G12, G15', required=True)
parser.add_argument('-d', '--dryrun', help='Dryrun.', action='store_true')
parser.add_argument('--prefix', help='filename prefix', default='randoms')
parser.add_argument('--nooverwrite',  help='Do not overwrite outputs if on disk', action='store_true')
parser.add_argument('-s', '--survey', help='Select survey', default='gama')

args        = parser.parse_args()
field       = args.field.upper()
dryrun      = args.dryrun
prefix      = args.prefix
survey      = args.survey.lower()
nooverwrite = args.nooverwrite

fields      = fetch_fields(survey)

assert  field in fields, f'Provided {field} field is not compatible with those available for {survey} survey ({fields})'

start   = time.time()

realz   = 0

fpath   = findfile(ftype='ddp', dryrun=dryrun, survey=survey, prefix=prefix)

dat     = Table.read(fpath)

runtime = calc_runtime(start, 'Reading {:.2f}M Gold DDP'.format(len(dat) / 1.e6), xx=dat)

fpath   = findfile(ftype='randoms_bd', dryrun=dryrun, field=field, survey=survey, prefix=prefix)
opath   = findfile(ftype='randoms_bd_ddp_n8', dryrun=dryrun, field=field, survey=survey, prefix=prefix)

if nooverwrite:
    overwrite_check(opath)
    
rand    = Table.read(fpath)
runtime = calc_runtime(start, 'Reading {:.2f}M randoms'.format(len(rand) / 1.e6), xx=rand)

# Propagate header 'DDP1_ZMIN' etc. to randoms.
rand.meta.update(dat.meta)

points       = np.c_[rand['CARTESIAN_X'], rand['CARTESIAN_Y'], rand['CARTESIAN_Z']]
points       = np.array(points, copy=True)

kd_tree_rand = KDTree(points)

del points 

gc.collect()

# Calculate DDP1/2/3 for each random. 
for idx in range(3):
    ddp_idx      = idx + 1

    runtime      = calc_runtime(start, 'Solving for DDP {}'.format(ddp_idx))
    
    ddp          = dat[dat['DDP'][:,idx] == 1]
    points_ddp   = np.c_[ddp['CARTESIAN_X'], ddp['CARTESIAN_Y'], ddp['CARTESIAN_Z']]
    points_ddp   = np.array(points_ddp, copy=True)
    
    kd_tree_ddp  = KDTree(points_ddp)    
    indexes_ddp  = kd_tree_rand.query_ball_tree(kd_tree_ddp, r=8.)

    rand['DDP{:d}_N8'.format(ddp_idx)] = np.array([len(idx) for idx in indexes_ddp])
                                      
ddp1_zmin           = dat.meta['DDP1_ZMIN']
ddp1_zmax           = dat.meta['DDP1_ZMAX']

ddp2_zmin           = dat.meta['DDP2_ZMIN']
ddp2_zmax           = dat.meta['DDP2_ZMAX']

ddp3_zmin           = dat.meta['DDP3_ZMIN']
ddp3_zmax           = dat.meta['DDP3_ZMAX']

print('Found redshift limits: {:.3f} < z < {:.3f}'.format(ddp1_zmin, ddp1_zmax))

# TODO: IN_DDP column akin to galaxies.
rand['DDPZLIMS']      = np.zeros(len(rand) * 3, dtype=int).reshape(len(rand), 3)

rand['DDPZLIMS'][:,0] = (rand['Z'].data > ddp1_zmin) & (rand['Z'].data < ddp1_zmax)
rand['DDPZLIMS'][:,1] = (rand['Z'].data > ddp2_zmin) & (rand['Z'].data < ddp2_zmax)
rand['DDPZLIMS'][:,2] = (rand['Z'].data > ddp3_zmin) & (rand['Z'].data < ddp3_zmax)

rand['DDP1_DELTA8'] = (rand['DDP1_N8'] / (rand.meta['VOL8'] * dat.meta['DDP1_DENS']) / rand['FILLFACTOR']) - 1.
rand['DDP2_DELTA8'] = (rand['DDP2_N8'] / (rand.meta['VOL8'] * dat.meta['DDP2_DENS']) / rand['FILLFACTOR']) - 1.
rand['DDP3_DELTA8'] = (rand['DDP3_N8'] / (rand.meta['VOL8'] * dat.meta['DDP3_DENS']) / rand['FILLFACTOR']) - 1.

rand['DDP1_DELTA8_TIER'] = delta8_tier(rand['DDP1_DELTA8'])

rand['DDP1_DELTA8_ZEROPOINT'] = ((1 + rand['DDP1_N8']) / (rand.meta['VOL8'] * dat.meta['DDP1_DENS']) / rand['FILLFACTOR']) - 1.
rand['DDP2_DELTA8_ZEROPOINT'] = ((1 + rand['DDP2_N8']) / (rand.meta['VOL8'] * dat.meta['DDP2_DENS']) / rand['FILLFACTOR']) - 1.
rand['DDP3_DELTA8_ZEROPOINT'] = ((1 + rand['DDP3_N8']) / (rand.meta['VOL8'] * dat.meta['DDP3_DENS']) / rand['FILLFACTOR']) - 1.

rand['DDP1_DELTA8_TIER_ZEROPOINT'] = delta8_tier(rand['DDP1_DELTA8_ZEROPOINT'])

for ii, xx in enumerate(d8_limits):
    rand.meta['D8{}LIMS'.format(ii)] = str(xx)

# TODO:  Handle bitmasks such that cut is not assumed to be fillfactor > 0.8 only.
rand = volfracs(rand)
        
runtime = calc_runtime(start, 'Writing {}'.format(opath), xx=rand)

rand.write(opath, format='fits', overwrite=True)

runtime = calc_runtime(start, 'Finished')
