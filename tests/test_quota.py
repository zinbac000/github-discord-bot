from github_discord_bot.quota import CreateQuota


def make(limit=3):
    now = [0.0]
    return CreateQuota(limit, clock=lambda: now[0]), now


def test_remaining_counts_down_per_user():
    quota, _ = make(3)
    assert quota.remaining(1) == 3
    assert quota.consume(1) is True
    assert quota.remaining(1) == 2
    assert quota.remaining(2) == 3  # someone else is unaffected


def test_cannot_pass_the_cap_and_nothing_is_counted_on_refusal():
    quota, _ = make(3)
    assert quota.consume(1, 2) is True
    assert quota.consume(1, 2) is False  # needs 2, only 1 left
    assert quota.remaining(1) == 1
    assert quota.consume(1) is True
    assert quota.remaining(1) == 0
    assert quota.consume(1) is False


def test_window_slides_after_an_hour():
    quota, now = make(2)
    quota.consume(1, 2)
    assert quota.remaining(1) == 0
    now[0] = 3599
    assert quota.remaining(1) == 0
    now[0] = 3600
    assert quota.remaining(1) == 2


def test_zero_means_no_cap():
    quota, _ = make(0)
    assert quota.remaining(1) is None
    assert quota.consume(1, 1000) is True


def test_idle_users_are_forgotten():
    quota, now = make(2)
    quota.consume(1)
    assert 1 in quota._used
    now[0] = 4000
    assert quota.remaining(1) == 2
    assert 1 not in quota._used
