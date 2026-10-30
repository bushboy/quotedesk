from eval.run_small_set import RESULTS, run


def test_the_small_set_replies_to_every_conversation():
    report = run()
    assert report["conversations"] == 20
    assert report["silent"] == 0
    assert RESULTS.is_file()
