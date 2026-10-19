from rg_music.pipeline import split_changes, suspicious_joins


def test_a_title_the_owner_had_joined_and_is_split_again_is_flagged():
    old = [{"title_key": "espana cani", "decision": "joined_by_owner"}, {"title_key": "hello", "decision": "split_by_credit"}]
    new = [{"title_key": "espana cani", "decision": "split_by_credit"}, {"title_key": "hello", "decision": "split_by_credit"},
           {"title_key": "rondo", "decision": "split_by_credit"}]
    assert [(c["title"], c["flag"]) for c in split_changes(old, new)] == [("espana cani", "LOST_OWNER_DECISION"), ("rondo", "")]


def test_a_new_track_joined_to_a_work_whose_credits_share_no_name_is_listed():
    track = lambda rid, key, artist: {"routine_id": rid, "track_no": "1", "work_key": key, "title": "Rondo", "artist": artist}  # noqa: E731
    old = [track("a", "rondo", "Alfred Schnittke")]
    new = old + [track("b", "rondo", "René Dupéré & Benoît Jutras"), track("c", "rondo", "Alfred Schnittke, Gidon Kremer")]
    assert [j["routine_id"] for j in suspicious_joins(old, new)] == ["b"]
