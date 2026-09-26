import re
from google.cloud import storage

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

if __name__ == "__main__":
    outgoing, incoming = load_graph()
    print("Outgoing links for node 0:", outgoing[0])
    print("Incoming links for node 0:", incoming[0])
    print("Out degree for node 0:", len(outgoing[0]))
    print("In degree for node 0:", len(incoming[0]))
    print("SUCCESS")