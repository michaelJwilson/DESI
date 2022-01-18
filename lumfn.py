import numpy as np

from   astropy.table import Table
from   cosmo import volcom


def lumfn(dat, Ms=np.arange(-25.5, -15.5, 0.1), Mcol='MCOLOR_0P0'):
    idxs   = np.digitize(dat[Mcol], bins=Ms)
    result = []

    ds     = np.diff(Ms)
    dM     = ds[0]

    assert np.all(ds == dM)
    
    vol    = dat.meta['VOLUME']

    for idx in np.arange(len(Ms) - 1):
        sample  = dat[idxs == idx]
        nsample = len(sample)
        
        median  = np.median(sample[Mcol])

        ivmax   = 1. / sample['VMAX'].data
        ivmax2  = 1. / sample['VMAX'].data**2.
        
        result.append([median,\
                       nsample / dM / vol,\
                       np.sqrt(nsample) / dM / vol,\
                       np.sum(ivmax) / dM,\
                       np.sqrt(np.sum(ivmax2)) / dM,\
                       nsample,
                       np.median(sample['VMAX'].data) / vol])

    names = ['MEDIAN_M', 'PHI_N', 'PHI_N_ERROR', 'PHI_IVMAX', 'PHI_IVMAX_ERROR', 'N', 'V_ON_VMAX']

    result = Table(np.array(result), names=names)
    result.meta.update(dat.meta)

    result.meta['MS'] = str(Ms.tolist())
    result.meta['VOLUME'] = vol

    return  result 
