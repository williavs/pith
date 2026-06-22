// Go extraction benchmark — multiple libraries, mirrors bench_python.py.
//
// Each extractor takes the same local HTML and returns clean content (markdown or
// text). Fetch/browser excluded — fair core comparison on identical fixtures.
//
//	go:trafilatura   markusmobius/go-trafilatura   — direct port of the trafilatura pith uses
//	go:readability   go-shiori/go-readability      — Mozilla-Readability port
//	go:domdistiller  markusmobius/go-domdistiller  — Chrome DOM Distiller port
//
// each emits an *html.Node / html string, rendered to markdown via html-to-markdown so
// byte counts are comparable to pith. (GoOse was dropped: its latest version moved the
// whole API into internal/ — no longer usable as a library.)
//
// CSV out: lang,fixture,ms_median,out_bytes
package main

import (
	"bytes"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	htmltomd "github.com/JohannesKaufmann/html-to-markdown"
	readability "github.com/go-shiori/go-readability"
	distiller "github.com/markusmobius/go-domdistiller"
	trafilatura "github.com/markusmobius/go-trafilatura"
	"golang.org/x/net/html"
)

const reps = 7

var (
	conv     = htmltomd.NewConverter("", true, nil)
	pageURL, _ = url.Parse("https://example.com/")
)

func toMD(htmlStr string) string {
	md, err := conv.ConvertString(htmlStr)
	if err != nil {
		return ""
	}
	return md
}

func viaTrafilatura(h string) string {
	res, err := trafilatura.Extract(strings.NewReader(h), trafilatura.Options{IncludeLinks: true})
	if err != nil || res == nil || res.ContentNode == nil {
		return ""
	}
	var buf bytes.Buffer
	if html.Render(&buf, res.ContentNode) != nil {
		return ""
	}
	return toMD(buf.String())
}

func viaReadability(h string) string {
	art, err := readability.FromReader(strings.NewReader(h), pageURL)
	if err != nil {
		return ""
	}
	return toMD(art.Content)
}

func viaDomDistiller(h string) string {
	res, err := distiller.ApplyForReader(strings.NewReader(h), nil)
	if err != nil || res == nil || res.Node == nil {
		return ""
	}
	var buf bytes.Buffer
	if html.Render(&buf, res.Node) != nil {
		return ""
	}
	return toMD(buf.String())
}

func main() {
	extractors := []struct {
		name string
		fn   func(string) string
	}{
		{"go:trafilatura", viaTrafilatura},
		{"go:readability", viaReadability},
		{"go:domdistiller", viaDomDistiller},
	}

	files, _ := filepath.Glob("../fixtures/*.html")
	sort.Strings(files)
	for _, f := range files {
		raw, err := os.ReadFile(f)
		if err != nil {
			continue
		}
		h := string(raw)
		base := filepath.Base(f)
		for _, ex := range extractors {
			out := ex.fn(h)
			times := make([]float64, 0, reps)
			for i := 0; i < reps; i++ {
				t := time.Now()
				ex.fn(h)
				times = append(times, float64(time.Since(t).Microseconds())/1000.0)
			}
			sort.Float64s(times)
			fmt.Printf("%s,%s,%.1f,%d\n", ex.name, base, times[len(times)/2], len(out))
		}
	}
}
