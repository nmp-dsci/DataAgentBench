from dab_bench.data.aliases import RELEASED_DATASETS, answer_file_name, dataset_key, query_key


def test_three_spellings_join_to_one_key() -> None:
    assert dataset_key("query_DEPS_DEV_V1") == "deps_dev_v1"
    assert dataset_key("DEPS_DEV_V1") == "deps_dev_v1"
    assert dataset_key("deps_dev") == "deps_dev_v1"
    assert dataset_key("music_brainz") == "music_brainz_20k"
    assert dataset_key("pancancer") == "pancancer_atlas"
    assert dataset_key("query_PATENTS") == "patents"


def test_query_key_accepts_every_upstream_form() -> None:
    assert query_key("crmarenapro", "1") == "crmarenapro/1"
    assert query_key("query_crmarenapro", "query1") == "crmarenapro/1"
    assert query_key("deps_dev", 2) == "deps_dev_v1/2"


def test_answer_file_names() -> None:
    assert answer_file_name("submissions/react_gpt-5.2.json") == "react_gpt-5.2"
    assert (
        answer_file_name("leaderboard_submissions/claude-opus-4-6_results.json")
        == "claude-opus-4-6"
    )


def test_released_set_is_the_leaderboard_twelve() -> None:
    assert len(RELEASED_DATASETS) == 12
    assert "cve" not in RELEASED_DATASETS


def test_a_trial_has_one_id_and_its_file_name_is_derived() -> None:
    from dab_bench.data.aliases import trace_stem, trial_id

    assert trial_id("deps_dev_v1/1", 1) == "deps_dev_v1/1/t1"
    # dataset keys carry underscores and digits; the file name still ends _<n>_t<k>
    assert trace_stem("deps_dev_v1/1", 1) == "deps_dev_v1_1_t1"
    assert trace_stem("pancancer_atlas/12", 3) == "pancancer_atlas_12_t3"
