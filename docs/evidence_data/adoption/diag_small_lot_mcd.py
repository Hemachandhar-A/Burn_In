import numpy as np
from generator.lot import generate_lot
from harness.variants import clean_family
from features.compute import compute
from module_a.scoring import compute_lot_raw, _sev_z_absolute
fam=clean_family("baseline")
for n in (15,30,40,50,77):
    z_fl=m_fl=tot=0; ms=[]
    for i in range(20):
        lot=generate_lot(f"D-{n}-{i}","PN-I2A",7101,account_id="i",family=fam,n_parts=n).dataset
        raw=compute_lot_raw(compute(lot))
        sz=_sev_z_absolute(raw.z); sm=raw.mcd_sev1
        # part-level max
        import pandas as pd
        df=pd.DataFrame({"c":raw.component_ids,"sz":sz,"sm":np.nan_to_num(sm,nan=-1)}).groupby("c").max()
        z_fl+=(df.sz>=2.956).sum(); m_fl+=(df.sm>=2.956).sum(); tot+=len(df)
    print(n,"z-only",round(z_fl/tot,4),"mcd-only",round(m_fl/tot,4),flush=True)
