#!/usr/bin/env python3
"""
short_tracks.py - поиск GPX-треков короче заданной длины.

Длина считается по точкам <trkpt> внутри каждого .gpx (формула гаверсинуса).
При переносе (-m) вместе с .gpx переносится парный <timestamp>.json,
если он лежит в той же папке (timestamp берётся из конца имени GPX).
Без аргументов выводится эта справка.
"""
import argparse, glob, shutil, os, sys
import xml.etree.ElementTree as ET
from math import radians, sin, cos, asin, sqrt

EPILOG = """\
примеры:
  %(prog)s .                            показать короткие треки в текущей папке
  %(prog)s ~/tracks                     показать короткие треки в ~/tracks
  %(prog)s ~/tracks -l 0.5              порог 500 м вместо 1 км
  %(prog)s ~/tracks -m ~/tracks/short   перенести короткие треки (и их .json)

замечания:
  без -m файлы только выводятся списком, ничего не перемещается;
  путь для -m берётся относительно текущей директории, а не папки с треками;
  повреждённые GPX выводятся как "ошибка" и пропускаются.
"""

def hav(a, b):
    la1, lo1, la2, lo2 = map(radians, (*a, *b))
    h = sin((la2-la1)/2)**2 + cos(la1)*cos(la2)*sin((lo2-lo1)/2)**2
    return 2 * 6371.0088 * asin(sqrt(h))

def track_len(path):
    pts = []
    for el in ET.parse(path).getroot().iter():
        if el.tag.endswith('trkpt'):
            pts.append((float(el.get('lat')), float(el.get('lon'))))
    return sum(hav(pts[i], pts[i+1]) for i in range(len(pts)-1))

ap = argparse.ArgumentParser(
    description="Найти GPX-треки короче заданной длины и при желании перенести их.",
    epilog=EPILOG,
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
ap.add_argument('folder', nargs='?', default='.',
                help="папка с треками (. - текущая)")
ap.add_argument('-m', '--move-to', metavar='DIR',
                help="папка, куда переносить короткие треки")
ap.add_argument('-l', '--limit', type=float, default=1.0, metavar='KM',
                help="порог в км (по умолчанию 1)")

if len(sys.argv) == 1:
    ap.print_help()
    sys.exit(0)

args = ap.parse_args()

if args.move_to:
    os.makedirs(args.move_to, exist_ok=True)

for path in sorted(glob.glob(os.path.join(args.folder, '*.gpx'))):
    name = os.path.basename(path)
    try:
        d = track_len(path)
    except Exception as e:
        print(f"{name}: ошибка {e}")
        continue
    if d < args.limit:
        print(f"{name}: {d*1000:.0f} м")
        if args.move_to:
            shutil.move(path, os.path.join(args.move_to, name))
            ts = name.rsplit('_', 1)[-1].replace('.gpx', '')
            js = os.path.join(args.folder, ts + '.json')
            if os.path.exists(js):
                shutil.move(js, os.path.join(args.move_to, ts + '.json'))
