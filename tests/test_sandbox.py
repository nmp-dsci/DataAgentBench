"""Each trial's Python sees only its own /work folder, so trials of one query stay independent.

Runs only where Docker and the sandbox image exist (`make sandbox`).
"""

from pathlib import Path

import pytest

from dab_bench.agent import sandbox as sbx

pytestmark = pytest.mark.skipif(not sbx.image_exists(), reason="no docker or no sandbox image")


def test_a_trial_cannot_see_another_trials_files(tmp_path: Path) -> None:
    box = sbx.Sandbox.start("isolation-test", workspace=tmp_path)
    try:
        out, _ = box.run("open('mine.txt', 'w').write('secret'); print('ok')", "yelp_1_t1")
        assert out.strip() == "ok"
        assert (tmp_path / "yelp_1_t1" / "mine.txt").read_text() == "secret"  # the run keeps it

        listing, _ = box.run("import os; print(sorted(os.listdir('/work')))", "yelp_1_t2")
        assert listing.strip() == "['yelp_1_t2']"
        peek, _ = box.run("print(open('/work/yelp_1_t1/mine.txt').read())", "yelp_1_t2")
        assert "secret" not in peek and "Error" in peek

        # the network is off too
        net, _ = box.run(
            "import socket\ntry:\n socket.create_connection(('1.1.1.1', 53), 2); print('open')\n"
            "except OSError as e:\n print('blocked')",
            "yelp_1_t2",
        )
        assert net.strip() == "blocked"
    finally:
        box.stop()
    assert box.live == {}
