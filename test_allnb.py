import papermill as pm


fields = ['G9', 'G12', 'G15']

# https://docs.pytest.org/en/6.2.x/
def test_allnbs():
    print('Running all tests.')
    
    # run_randomqa()

    run_goldqa()

    run_delta8qa()
    
    print('Done.')
    
def run_randomqa():
    for field in fields:
        print('Running random QA for field {}'.format(field))
        
        pm.execute_notebook('docs/nb/randoms_qa.ipynb',\
                            'test/pm_randoms_qa_{}.ipynb'.format(field),\
                            parameters=dict(field=field),\
                            kernel='lumfn',\
                            )

def run_goldqa():
    print('Running gold QA')

    pm.execute_notebook('docs/nb/zmax_catQA.ipynb',\
                            'test/zmax_catQA.ipynb',\
                            kernel='lumfn',\
                            )

    pm.execute_notebook('docs/nb/kE_catQA.ipynb',\
                        'test/kE_catQA.ipynb',\
                        kernel='lumfn',\
                        )

    pm.execute_notebook('docs/nb/ddp_QA.ipynb',\
                        'test/ddp_QA.ipynb',\
                        kernel='lumfn',\
                        )

    pm.execute_notebook('docs/nb/delta8_qa.ipynb',\
                        'test/delta8_qa.ipynb',\
                        kernel='lumfn',\
                        )

    # jack knife qa. 
    # schechter fit. 
    # d8 LF. 
    # desi qa. 
    
def run_delta8qa():
    for field in fields:
        print('Running delta8 QA for field {}'.format(field))

        pm.execute_notebook('docs/nb/delta8_qa.ipynb',\
                            'test/pm_delta8_qa_{}.ipynb'.format(field),\
                            parameters=dict(field=field),\
                            kernel='lumfn',\
                            )
