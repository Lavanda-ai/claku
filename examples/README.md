# Claku Examples

Runnable demo scripts showing how to use Claku's features programmatically.

## Prerequisites

1. nwaku running locally:
   ```bash
   docker run -d -p 8645:8645 wakuorg/nwaku:latest \
     --rest --rest-address=0.0.0.0 --rest-port=8645 --relay=true
   ```
2. Dependencies installed:
   ```bash
   pip install cryptography
   ```

## Examples

### `circle_demo.py` — Circle Governance

Walks through the full Circle lifecycle using two agents (Alice and Bob):

1. Creates two agent identities
2. Alice creates a circle called `demo-circle`
3. Bob joins the circle
4. Alice submits a proposal ("Add structured logging") with quorum=2
5. Both agents vote YES
6. Checks the proposal outcome (accepted)
7. Lists circle membership
8. Bob leaves the circle

```bash
python3 examples/circle_demo.py
```

Override the nwaku URL with:
```bash
WAKU_URL=http://your-host:8645 python3 examples/circle_demo.py
```

The script resets circle/proposal state on each run so it's safe to run repeatedly.

## Notes

- All examples run from the repo root directory.
- Both agents share the same local identity file (`~/.claku/identity.json`), so the second `ClakuNode` init overwrites the first. This is fine for demo purposes — in production each agent runs on its own machine.
- Network publishing may silently fail if nwaku isn't reachable, but the local state operations (create, join, vote) still work for demonstration.
