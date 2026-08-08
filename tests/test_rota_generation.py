"""End-to-end rota generation through the /rota route."""

from gbtalks.models import Talk


def _build_festival(make_talk, make_recorder, n_priority=6, n_recorders=3):
    for i in range(n_recorders):
        make_recorder(name=f"Recorder {i}", max_shifts_per_day=2)

    for i in range(n_priority):
        make_talk(
            talk_id=i + 1,
            title=f"Priority Talk {i}",
            day="Saturday",
            start=f"{9 + i:02d}:00",
            end=f"{10 + i:02d}:00",
            venue=f"Venue {i % 3}",
            is_priority=True,
            is_rotaed=True,
        )


class TestRotaGeneration:
    def test_assigns_priority_talks(self, auth_client, db, make_talk, make_recorder):
        _build_festival(make_talk, make_recorder)

        response = auth_client.post("/rota", follow_redirects=True)
        assert response.status_code == 200

        assigned = Talk.query.filter(Talk.recorder_name.isnot(None)).count()
        total = Talk.query.count()
        assert assigned > 0, f"0 of {total} talks were assigned"

    def test_reports_the_assignments_it_made(
        self, auth_client, db, make_talk, make_recorder
    ):
        _build_festival(make_talk, make_recorder)

        body = auth_client.post("/rota", follow_redirects=True).get_data(as_text=True)
        assert "Assigned 0/" not in body, body[body.find("Assigned") - 60 :][:200]


class TestRotaFromSampleData:
    """The shipped sample data must produce a usable rota.

    Loading it and generating previously reported "Assigned 0/28 ... 0/47",
    because every sample talk had is_rotaed unset.
    """

    def test_generates_a_rota_end_to_end(self, app, auth_client, db):
        runner = app.test_cli_runner()
        runner.invoke(args=["load-sample-data", "recorders"])
        runner.invoke(args=["load-sample-data", "talks"])

        response = auth_client.post("/rota", follow_redirects=True)
        assert response.status_code == 200

        assigned = Talk.query.filter(Talk.recorder_name.isnot(None)).count()
        assert assigned > 0, "the sample data produced an empty rota"

    def test_picks_up_unflagged_talks_a_recorder_is_already_there_for(
        self, app, auth_client, db
    ):
        """is_rotaed decides what the rota is *built around*, not what may be
        recorded.

        The two main loops only seek out recorders for flagged talks
        (rota/routes.py:266 and :302). The follow-on queries (:275 and :313)
        deliberately do not filter on is_rotaed: once a recorder is in a venue
        anyway, staying on for the next talk costs nothing, so an unflagged
        talk is worth picking up.
        """
        runner = app.test_cli_runner()
        runner.invoke(args=["load-sample-data", "recorders"])
        runner.invoke(args=["load-sample-data", "talks"])

        auth_client.post("/rota", follow_redirects=True)

        unflagged_but_assigned = Talk.query.filter(
            Talk.is_rotaed.is_(False), Talk.recorder_name.isnot(None)
        ).all()

        assert unflagged_but_assigned, "no free extra talks were picked up"

        # Each one must have gone to a recorder who was already working that
        # day, rather than having been sought out on its own account.
        for talk in unflagged_but_assigned:
            same_day_talks = [
                other
                for other in Talk.query.filter(
                    Talk.recorder_name == talk.recorder_name, Talk.id != talk.id
                )
                if other.start_time.date() == talk.start_time.date()
            ]
            assert same_day_talks, (
                f"talk {talk.id} was assigned to {talk.recorder_name}, who has no "
                f"other talk that day - it was not a free pick-up"
            )
