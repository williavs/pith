"""pith CLI:  pith <url> [objective] [--full] [--js]"""
import argparse

from .core import Extractor


def main() -> None:
    ap = argparse.ArgumentParser(prog="pith", description="URL -> clean LLM-ready markdown (free).")
    ap.add_argument("url")
    ap.add_argument("objective", nargs="?", help="optional: return only passages answering this (needs GROQ_API_KEY)")
    ap.add_argument("--full", action="store_true", help="include full page markdown")
    ap.add_argument("--js", action="store_true", help="force a real browser (JS-rendered / bot-protected pages)")
    args = ap.parse_args()

    render_js = True if args.js else "auto"
    out = Extractor().extract(urls=[args.url], objective=args.objective, full_content=args.full, render_js=render_js)
    for r in out.results:
        if r.title:
            print(f"# {r.title}")
        if r.publish_date:
            print(f"_{r.publish_date}_\n")
        for e in r.excerpts:
            print(e)
    for err in out.errors:
        print(f"[error] {err['url']}: {err['error']}")


if __name__ == "__main__":
    main()
