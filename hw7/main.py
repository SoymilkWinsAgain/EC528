import argparse
import re
from collections import Counter
from time import perf_counter

import apache_beam as beam
from apache_beam.io import fileio
from apache_beam.io.filesystems import FileSystems
from apache_beam.options.pipeline_options import PipelineOptions
from apache_beam.runners.runner import PipelineState


def read_page(file):
    name = file.metadata.path.rsplit("/", 1)[-1]
    html = file.read_utf8()

    links = re.findall(r'HREF="(\d+\.html)"', html, re.IGNORECASE)

    text = re.sub(r"<[^>]+>", " ", html)
    words = re.findall(r"[a-z]+", text.lower())

    trigrams = Counter(
        " ".join(words[i:i + 3])
        for i in range(len(words) - 2)
    )

    return name, links, trigrams


def incoming_pairs(page):
    name, links, _ = page

    # Include files with zero incoming links
    yield name, 0

    for target in links:
        yield target, 1


def ranking(item):
    name, count = item
    return -count, name


def format_top(rows):
    return "\n".join(
        f"{name}\t{count}"
        for name, count in sorted(rows, key=ranking)
    )


def write_top(counts, label, output):
    (
        counts
        | f"{label}: top five"
        >> beam.combiners.Top.Smallest(5, key=ranking)
        | f"{label}: format"
        >> beam.Map(format_top)
        | f"{label}: write"
        >> beam.io.WriteToText(
            f"{output}/{label}",
            file_name_suffix=".txt",
            shard_name_template="",
            num_shards=1,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="gs://ec528hw2/pages/*.html",
    )
    parser.add_argument("--output", required=True)
    args, beam_args = parser.parse_known_args()

    options = PipelineOptions(beam_args)
    start = perf_counter()

    p = beam.Pipeline(options=options)

    pages = (
        p
        | "Find HTML files"
        >> fileio.MatchFiles(
            args.input,
            empty_match_treatment=fileio.EmptyMatchTreatment.DISALLOW,
        )
        | "Distribute files" >> beam.Reshuffle()
        | "Open files" >> fileio.ReadMatches()
        | "Read and parse pages" >> beam.Map(read_page)
    )

    incoming = (
        pages
        | "Incoming pairs" >> beam.FlatMap(incoming_pairs)
        | "Count incoming links" >> beam.CombinePerKey(sum)
    )

    outgoing = (
        pages
        | "Count outgoing links"
        >> beam.Map(lambda page: (page[0], len(page[1])))
    )

    trigrams = (
        pages
        | "Per-file trigram counts"
        >> beam.FlatMap(lambda page: page[2].items())
        | "Total trigram counts" >> beam.CombinePerKey(sum)
    )

    write_top(incoming, "incoming", args.output)
    write_top(outgoing, "outgoing", args.output)
    write_top(trigrams, "trigrams", args.output)

    result = p.run()
    state = result.wait_until_finish()

    if state != PipelineState.DONE:
        raise RuntimeError(f"Pipeline failed: {state}")

    elapsed = perf_counter() - start

    print(f"\nRunner: {options.get_all_options()['runner']}")
    print(f"Runtime: {elapsed:.2f} seconds")

    for label in ["incoming", "outgoing", "trigrams"]:
        print(f"\nTop 5 {label}:")
        with FileSystems.open(f"{args.output}/{label}.txt") as f:
            print(f.read().decode("utf-8"))


if __name__ == "__main__":
    main()