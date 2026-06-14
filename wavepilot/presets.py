"""Preset channel groups for WavePilot SDR."""

PRESET_GROUPS = [
    {
        "id": "weather",
        "name": "NOAA Weather",
        "mode": "nfm",
        "channels": [
            {"name": "WX1", "mhz": 162.400},
            {"name": "WX2", "mhz": 162.425},
            {"name": "WX3", "mhz": 162.450},
            {"name": "WX4", "mhz": 162.475},
            {"name": "WX5", "mhz": 162.500},
            {"name": "WX6", "mhz": 162.525},
            {"name": "WX7", "mhz": 162.550},
        ],
    },
    {
        "id": "airband",
        "name": "Airband",
        "mode": "am",
        "channels": [
            {"name": "Tower", "mhz": 118.000},
            {"name": "Ground", "mhz": 121.700},
            {"name": "Emergency", "mhz": 121.500},
            {"name": "Unicom", "mhz": 122.800},
            {"name": "Approach", "mhz": 125.000},
            {"name": "Center", "mhz": 127.000},
        ],
    },
    {
        "id": "fm",
        "name": "FM Broadcast",
        "mode": "wfm",
        "channels": [
            {"name": "FM 88.1", "mhz": 88.100},
            {"name": "FM 92.5", "mhz": 92.500},
            {"name": "FM 97.1", "mhz": 97.100},
            {"name": "FM 101.1", "mhz": 101.100},
            {"name": "FM 104.3", "mhz": 104.300},
            {"name": "FM 107.3", "mhz": 107.300},
        ],
    },
    {
        "id": "marine",
        "name": "Marine VHF",
        "mode": "nfm",
        "channels": [
            {"name": "Ch 06 Safety", "mhz": 156.300},
            {"name": "Ch 13 Bridge", "mhz": 156.650},
            {"name": "Ch 16 Distress", "mhz": 156.800},
            {"name": "Ch 22A USCG", "mhz": 157.100},
            {"name": "AIS 1", "mhz": 161.975},
            {"name": "AIS 2", "mhz": 162.025},
        ],
    },
    {
        "id": "ham",
        "name": "Ham + Space",
        "mode": "nfm",
        "channels": [
            {"name": "2m Calling", "mhz": 146.520},
            {"name": "APRS", "mhz": 144.390},
            {"name": "70cm Calling", "mhz": 446.000},
            {"name": "ISS Voice", "mhz": 145.800},
            {"name": "NOAA APT 19", "mhz": 137.100},
            {"name": "433 ISM", "mhz": 433.920},
        ],
    },
    {
        "id": "frs-gmrs",
        "name": "FRS / GMRS",
        "mode": "nfm",
        "channels": [
            {"name": "FRS 1", "mhz": 462.5625},
            {"name": "FRS 3", "mhz": 462.6125},
            {"name": "FRS 7", "mhz": 462.7125},
            {"name": "FRS 15", "mhz": 462.5500},
            {"name": "FRS 17", "mhz": 462.6000},
            {"name": "FRS 20", "mhz": 462.6750},
        ],
    },
    {
        "id": "murs-business",
        "name": "MURS + Business",
        "mode": "nfm",
        "channels": [
            {"name": "MURS 1", "mhz": 151.820},
            {"name": "MURS 2", "mhz": 151.880},
            {"name": "MURS 3", "mhz": 151.940},
            {"name": "Blue Dot", "mhz": 154.570},
            {"name": "Green Dot", "mhz": 154.600},
            {"name": "Biz 464.5", "mhz": 464.500},
        ],
    },
    {
        "id": "data-oddities",
        "name": "Data + Oddities",
        "mode": "am",
        "channels": [
            {"name": "ADS-B", "mhz": 1090.000},
            {"name": "Pager 929", "mhz": 929.000},
            {"name": "Rail 07", "mhz": 160.215},
            {"name": "Rail 36", "mhz": 160.650},
            {"name": "ISM 915", "mhz": 915.000},
            {"name": "NOAA HRPT", "mhz": 1698.000},
        ],
    },
]


def all_presets():
    return {"groups": PRESET_GROUPS}


def group_by_id(group_id):
    for group in PRESET_GROUPS:
        if group["id"] == group_id:
            return group
    return None


def flat_channels(group_id="all"):
    if group_id and group_id != "all":
        group = group_by_id(group_id)
        groups = [group] if group else []
    else:
        groups = PRESET_GROUPS

    channels = []
    for group in groups:
        for channel in group["channels"]:
            item = dict(channel)
            item["group"] = group["name"]
            item["group_id"] = group["id"]
            item["mode"] = group["mode"]
            item["hz"] = int(round(float(item["mhz"]) * 1_000_000))
            channels.append(item)
    return channels
