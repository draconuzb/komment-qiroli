#!/usr/bin/env python3
"""Modem pool'ni terminaldan boshqarish (panelsiz, headless mini-PC uchun).

Misollar:
    python modem_cli.py detect              # modemga o'xshash interfeyslar
    python modem_cli.py add 192.168.8.100 --label Beeline-1 \
           --rotate huawei --url http://192.168.8.1
    python modem_cli.py list
    python modem_cli.py config               # 3proxy.cfg yaratadi
    python modem_cli.py ip m1                # m1 modemning tashqi IP'si
    python modem_cli.py rotate m1            # m1 IP'sini yangilaydi
    python modem_cli.py assign-all           # akkauntlarni modemlarga taqsimlaydi
"""
import argparse
import sys

import modem_pool


def main() -> int:
    p = argparse.ArgumentParser(description="Komment Qiroli — modem pool CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("detect", help="Modemga o'xshash interfeyslarni aniqlash")

    a = sub.add_parser("add", help="Modem qo'shish")
    a.add_argument("ext_ip", help="Modemning host'dagi chiquvchi IP'si")
    a.add_argument("--label", default="", help="Nom (mas: Beeline-1)")
    a.add_argument("--rotate", default="", choices=["", "huawei", "adb"], help="Rotation turi")
    a.add_argument("--url", default="", help="Huawei API url (http://192.168.8.1)")
    a.add_argument("--serial", default="", help="ADB serial")

    sub.add_parser("list", help="Modemlar ro'yxati")
    sub.add_parser("config", help="3proxy.cfg yaratish")
    sub.add_parser("assign-all", help="Barcha akkauntlarni modemlarga taqsimlash")

    r = sub.add_parser("rotate", help="Modem IP'sini yangilash")
    r.add_argument("modem_id")

    i = sub.add_parser("ip", help="Modemning tashqi IP'si")
    i.add_argument("modem_id")

    d = sub.add_parser("rm", help="Modemni o'chirish")
    d.add_argument("modem_id")

    args = p.parse_args()

    if args.cmd == "detect":
        cands = modem_pool.detect_candidates()
        if not cands:
            print("Modemga o'xshash interfeys topilmadi.")
            return 0
        for c in cands:
            print(f"  {c['iface']:12} ext_ip={c['ext_ip']:16} rotate_url≈{c['guess_rotate_url']}")
        return 0

    if args.cmd == "add":
        rotate = {}
        if args.rotate == "huawei" and args.url:
            rotate = {"type": "huawei", "url": args.url}
        elif args.rotate == "adb":
            rotate = {"type": "adb", "serial": args.serial}
        m = modem_pool.add_modem(args.ext_ip, rotate=rotate, label=args.label)
        print(f"Qo'shildi: {m['id']} ({m['label']}) → socks5://{modem_pool.PROXY_HOST}:{m['port']}")
        return 0

    if args.cmd == "rm":
        modem_pool.remove_modem(args.modem_id)
        print(f"{args.modem_id} o'chirildi.")
        return 0

    if args.cmd == "list":
        modems = modem_pool.list_modems()
        if not modems:
            print("Modem yo'q.")
            return 0
        for m in modems:
            print(f"  {m['id']:4} {m['label']:14} {m['proxy']:28} "
                  f"ext={m['ext_ip']:16} akk={m['accounts']:2} rot={m['rotate_type'] or '-'}")
        return 0

    if args.cmd == "config":
        path = modem_pool.write_3proxy_config()
        print(f"3proxy config saqlandi: {path}")
        print("Ishga tushirish:  3proxy " + path)
        return 0

    if args.cmd == "assign-all":
        import instagram_client
        if not modem_pool.has_modems():
            print("Avval modem qo'shing.")
            return 1
        for acc in instagram_client.list_accounts():
            u = acc["username"]
            modem_pool.assign(u)
            instagram_client.set_proxy(u, modem_pool.proxy_for(u))
            print(f"  @{u} → {modem_pool.proxy_for(u)}")
        return 0

    if args.cmd == "ip":
        print(modem_pool.current_ip(args.modem_id))
        return 0

    if args.cmd == "rotate":
        modem_pool.rotate(args.modem_id)
        print("Yangi IP:", modem_pool.current_ip(args.modem_id))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
