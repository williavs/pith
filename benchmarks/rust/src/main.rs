// Rust extraction benchmark — multiple libraries, mirrors bench_python.py / go main.go.
//
//   rust:trafilatura  trafilatura (0.3, markdown feat) — direct port of the trafilatura pith uses
//   rust:dom_smoothie dom_smoothie (0.18)              — Mozilla-Readability port, native markdown
//   rust:readability  readability (0.3)                — arc90/readability port, needs htmd for markdown
//
// Same fixtures, same protocol. Fetch/browser excluded.
// CSV out: lang,fixture,ms_median,out_bytes
use std::fs;
use std::io::Cursor;
use std::time::Instant;

use dom_smoothie::{Config, Readability, TextMode};

const REPS: usize = 7;

fn via_trafilatura(html: &str) -> String {
    let mut opts = trafilatura::Options::default();
    opts.include_links = true;
    match trafilatura::extract(html, &opts) {
        Ok(res) => res.content_markdown(),
        Err(_) => String::new(),
    }
}

fn via_dom_smoothie(html: &str) -> String {
    let cfg = Config { text_mode: TextMode::Markdown, ..Default::default() };
    match Readability::new(html, None, Some(cfg)).and_then(|mut r| r.parse()) {
        Ok(article) => article.text_content.to_string(),
        Err(_) => String::new(),
    }
}

fn via_readability(html: &str) -> String {
    let url = url::Url::parse("https://example.com/").unwrap();
    let mut cursor = Cursor::new(html.as_bytes());
    match readability::extractor::extract(&mut cursor, &url) {
        Ok(product) => htmd::convert(&product.content).unwrap_or_default(),
        Err(_) => String::new(),
    }
}

fn main() {
    let extractors: [(&str, fn(&str) -> String); 3] = [
        ("rust:trafilatura", via_trafilatura),
        ("rust:dom_smoothie", via_dom_smoothie),
        ("rust:readability", via_readability),
    ];

    let mut files: Vec<_> = fs::read_dir("../fixtures")
        .unwrap()
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().map(|x| x == "html").unwrap_or(false))
        .collect();
    files.sort();

    for path in files {
        let html = fs::read_to_string(&path).unwrap_or_default();
        let name = path.file_name().unwrap().to_string_lossy();
        for (lang, f) in extractors.iter() {
            let out = f(&html);
            let mut times: Vec<f64> = Vec::with_capacity(REPS);
            for _ in 0..REPS {
                let t = Instant::now();
                let _ = f(&html);
                times.push(t.elapsed().as_secs_f64() * 1000.0);
            }
            times.sort_by(|a, b| a.partial_cmp(b).unwrap());
            println!("{},{},{:.1},{}", lang, name, times[times.len() / 2], out.len());
        }
    }
}
