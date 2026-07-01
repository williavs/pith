// Cross-language pressure test for the pith HTTP API. Go client, goroutine-per-worker,
// fixed concurrency, fixed duration. Proves pith serves any language and measures how it
// holds up under sustained concurrent load.
//
//	go run benchmarks/loadtest.go -url http://127.0.0.1:8900/verify-email \
//	   -body '{"email":"jane@acme.com"}' -c 50 -d 10s
//
// Reports: throughput (req/s), latency p50/p95/p99/max, and error count.
package main

import (
	"bytes"
	"flag"
	"fmt"
	"io"
	"net/http"
	"sort"
	"sync"
	"sync/atomic"
	"time"
)

func main() {
	url := flag.String("url", "http://127.0.0.1:8900/verify-email", "endpoint")
	body := flag.String("body", `{"email":"jane@acme.com"}`, "JSON request body")
	conc := flag.Int("c", 50, "concurrent workers")
	dur := flag.Duration("d", 10*time.Second, "test duration")
	flag.Parse()

	// keep-alive connection pool sized to the worker count — reuse, don't reconnect
	client := &http.Client{
		Timeout: 60 * time.Second,
		Transport: &http.Transport{MaxIdleConns: *conc, MaxIdleConnsPerHost: *conc, MaxConnsPerHost: *conc},
	}

	var ok, errs int64
	var mu sync.Mutex
	lat := make([]time.Duration, 0, 100000)
	deadline := time.Now().Add(*dur)
	var wg sync.WaitGroup
	start := time.Now()

	for i := 0; i < *conc; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for time.Now().Before(deadline) {
				t0 := time.Now()
				resp, err := client.Post(*url, "application/json", bytes.NewReader([]byte(*body)))
				if err != nil {
					atomic.AddInt64(&errs, 1)
					continue
				}
				io.Copy(io.Discard, resp.Body) // must drain for keep-alive reuse
				resp.Body.Close()
				el := time.Since(t0)
				if resp.StatusCode == 200 {
					atomic.AddInt64(&ok, 1)
					mu.Lock()
					lat = append(lat, el)
					mu.Unlock()
				} else {
					atomic.AddInt64(&errs, 1)
				}
			}
		}()
	}
	wg.Wait()
	wall := time.Since(start)

	sort.Slice(lat, func(i, j int) bool { return lat[i] < lat[j] })
	pct := func(p float64) time.Duration {
		if len(lat) == 0 {
			return 0
		}
		i := int(p / 100 * float64(len(lat)))
		if i >= len(lat) {
			i = len(lat) - 1
		}
		return lat[i]
	}
	fmt.Printf("\npith load test — %s\n", *url)
	fmt.Printf("  concurrency %d · duration %s\n", *conc, wall.Round(time.Millisecond))
	fmt.Printf("  requests    %d ok, %d errors\n", ok, errs)
	fmt.Printf("  throughput  %.0f req/s\n", float64(ok)/wall.Seconds())
	fmt.Printf("  latency     p50 %s · p95 %s · p99 %s · max %s\n",
		pct(50).Round(time.Microsecond), pct(95).Round(time.Microsecond),
		pct(99).Round(time.Microsecond), pct(100).Round(time.Microsecond))
}
