from random import Random
from domain.channel import patch_mutex
from domain.soundboard import points, windows
from domain.states import FEATURES
from domain.venues import VENUES

# 两场演练重用同一套麦位编号、线路名和声检刻度；venue 是真正的隔离边界。
PLACES = [
    ("MIC-PAV","东门棚台","TAG-E01","BUS-A"),
    ("MIC-WALK","西风雨连廊","TAG-W09","BUS-A"),
    ("MIC-INFO","入口咨询桌","TAG-Z03","BUS-A"),
    ("MIC-HUB","室内总音控","TAG-N26","BUS-B"),
]


def capture(venue,code, location, slot, frequency, levels, purpose="live"):
    channel=next(item[3] for item in PLACES if item[0]==location)
    return {"venue":venue,"code":code,"point":location,"channel":channel,"revision":1,"slot":slot,
            "frequency":frequency,"purpose":purpose,**dict(zip(FEATURES,levels,strict=True))}


def bench(venue, seed):
    rng=Random(seed)
    return [capture(venue,f"REF-{index+1:02}",PLACES[index%4][0],index+1,550+index*13,
                    [max(.03,min(.42,rng.gauss(center,.033))) for center in (.20,.24,.30,.15)],"baseline")
            for index in range(32)]


def site_a_fixtures():
    return [
        capture("SITE-A","WIN-C-01","MIC-PAV",80,1320,(.79,.73,.55,.59)),
        capture("SITE-A","WIN-C-02","MIC-WALK",80,1324,(.80,.72,.57,.53)),
        capture("SITE-A","WIN-C-03","MIC-INFO",80,1311,(.83,.74,.56,.57)),
        capture("SITE-A","WIN-L-01","MIC-HUB",82,2210,(.91,.87,.62,.70)),
        capture("SITE-A","WIN-N-01","MIC-WALK",84,730,(.22,.25,.31,.15)),
    ]


def site_b_fixtures():
    # 二号场刻意复用一号场的窗编号与刻度，证明两场同号可各自保存、互不覆盖。
    return [
        capture("SITE-B","WIN-C-01","MIC-PAV",80,1318,(.77,.71,.54,.58)),
        capture("SITE-B","WIN-C-02","MIC-WALK",80,1325,(.79,.70,.55,.52)),
        capture("SITE-B","WIN-C-03","MIC-INFO",80,1312,(.81,.73,.55,.56)),
        capture("SITE-B","WIN-L-01","MIC-HUB",82,900,(.24,.27,.33,.18)),
    ]


def _table_rows():
    rows = {
        patch_mutex: [{"venue": venue, "code": 1} for venue in VENUES],
        points: [{"venue": "SITE-A", "code": code, "location": name, "mic_tag": f"{tag}-A",
                  "channel": channel} for code, name, tag, channel in PLACES]
                + [{"venue": "SITE-B", "code": code, "location": name, "mic_tag": f"{tag}-B",
                    "channel": channel} for code, name, tag, channel in PLACES],
        windows: bench("SITE-A", 217) + site_a_fixtures()
                 + bench("SITE-B", 432) + site_b_fixtures(),
    }
    return tuple((table, table_rows) for table, table_rows in rows.items())


FIXTURES = _table_rows()
