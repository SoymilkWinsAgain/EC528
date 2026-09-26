import re
from google.cloud import storage
from time import perf_counter
import numpy as np
from collections import deque
import json

N = 12000
link_pattern = re.compile(r'HREF="(\d+)\.html"', re.IGNORECASE)

def load_graph():
    client = storage.Client()
    outgoing = [[] for _ in range(N)]
    incoming = [[] for _ in range(N)]
    blobs = client.list_blobs("ec528hw2", prefix="pages/")

    for blob in blobs:
        filename = blob.name.rsplit("/", 1)[-1]
        node = int(filename[:-5])
        text = blob.download_as_text(encoding="utf-8")
        links = [int(x) for x in link_pattern.findall(text)]
        outgoing[node] = links

        for target in links:
            incoming[target].append(node)

    return outgoing, incoming


def compute_statistics(x):
    return {
        "mean": np.mean(x),
        "std": np.std(x, ddof=1),
        "min": np.min(x),
        "max": np.max(x),
        "median": np.median(x),
        "q20": np.percentile(x, 20),
        "q40": np.percentile(x, 40),
        "q60": np.percentile(x, 60),
        "q80": np.percentile(x, 80)
    }
    
    
def page_rank(outgoing, incoming, n=N, tolerance=0.005):
    pr = [1.0 / n for _ in range(n)]
    iteration = 0
    max_iter = 1000

    while True:
        new_pr = [0.15 / n for _ in range(n)]

        for node in range(n):
            score = 0.0
            for source in incoming[node]:
                score += pr[source]/ len(outgoing[source])
            new_pr[node] += 0.85 * score
            
        old_sum = sum(pr)
        new_sum = sum(new_pr)
        relative_change = abs(new_sum - old_sum) / old_sum
        iteration += 1
        pr = new_pr

        if relative_change <= tolerance or iteration >= max_iter:
            break

    return pr


def closeness_centrality(outgoing, start, n=N):
    distances = [-1] * n
    distances[start] = 0
    queue = deque([start])
    reached = 1
    total_distance = 0

    while queue:
        node = queue.popleft()
        next_distance = distances[node] + 1

        for neighbor in outgoing[node]:
            if distances[neighbor] != -1:
                continue

            distances[neighbor] = next_distance
            total_distance += next_distance
            reached += 1
            queue.append(neighbor)

    if reached != n:
        return 0.0

    return (n - 1) / total_distance
    

if __name__ == "__main__":
    start_time = perf_counter()
    
    # tests
    test_outgoing = [[1, 2], [0], [0, 1]]
    test_incoming = [[1, 2], [0, 2], [0]]
    test_pr = page_rank(test_outgoing, test_incoming, n=len(test_outgoing))
    print("Test PageRank:", test_pr)
    assert np.allclose(test_pr, [0.475, 1/3, 23/120])
    test_cc = [closeness_centrality(test_outgoing, i, n=len(test_outgoing)) for i in range(len(test_outgoing))]
    print("Test Closeness Centrality:", test_cc)
    assert np.allclose(test_cc, [1.0, 2/3, 1.0])
    
    outgoing, incoming = load_graph()
    
    # compute degree statistics
    out_degrees = np.array([len(x) for x in outgoing])
    in_degrees = np.array([len(x) for x in incoming])
    out_stats = compute_statistics(out_degrees)
    in_stats = compute_statistics(in_degrees)
    print("Out degree statistics:", out_stats)
    print("In degree statistics:", in_stats)
    
    # compute PageRank and closeness centrality for the loaded graph
    pr = page_rank(outgoing, incoming, n=len(outgoing))
    cc = [closeness_centrality(outgoing, i, n=len(outgoing)) for i in range(len(outgoing))]
    
    top5 = sorted(range(len(pr)), key=lambda i: pr[i], reverse=True)[:5]
    print("Top 5 PageRank:")
    for node in top5:
        print(node, pr[node])
        
    best_cc_node = int(np.argmax(cc))
    print("Best Closeness Centrality:", best_cc_node, cc[best_cc_node])
    
    end_time = perf_counter()
    total_time = end_time - start_time
    print(f"Total time: {total_time:.2f} seconds")
    
    results = {
        "out_degree_statistics": {k: float(v) for k, v in out_stats.items()},
        "in_degree_statistics": {k: float(v) for k, v in in_stats.items()},
        "pagerank": pr,
        "pagerank_top5": [
            {
                "node": int(node),
                "score": float(pr[node])
            }
            for node in top5
        ],
        "closeness_centrality": cc,
        "best_closeness_node": int(best_cc_node),
        "best_closeness_score": float(cc[best_cc_node]),
        "total_time_seconds": total_time
    }

    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)