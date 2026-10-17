"""Bob, an AI accounting associate (MONEY TALKS 2 hackathon build of the ledger-native close).

Bob runs the month-end close on a QuickBooks company: reads the ledger, ties every bank and card statement to it, checks
it, fixes what it can cite, builds a workpaper for every balance-sheet account and asks a person about the rest. The
hackathon build routes every model call through Nicrron (bob/config.py, product/reasoning/providers.py) and reports every
run, step by step, to PRISM by Block Convey (bob/trace.py). The engine itself is unchanged: ops/native/*."""

VERSION = "v2"                                            # bumped when Bob's accounting behaviour changes (bob/eval/CHANGES.md)
