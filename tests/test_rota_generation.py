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

    def test_mostly_assigns_only_talks_flagged_for_the_rota(self, app, auth_client, db):
        """KNOWN BUG: the follow-on assignment paths ignore is_rotaed.

        The two main loops skip talks that are not flagged (rota/routes.py:266
        and :302), but the queries that assign same-venue and nearby talks to a
        recorder already on shift (:275 and :313) do not filter on it. So a
        handful of talks marked "not in rota" still get a recorder.

        This pins the current behaviour; it is not an endorsement of it.
        """
        runner = app.test_cli_runner()
        runner.invoke(args=["load-sample-data", "recorders"])
        runner.invoke(args=["load-sample-data", "talks"])

        auth_client.post("/rota", follow_redirects=True)

        unflagged_but_assigned = Talk.query.filter(
            Talk.is_rotaed.is_(False), Talk.recorder_name.isnot(None)
        ).count()
        assigned = Talk.query.filter(Talk.recorder_name.isnot(None)).count()

        assert unflagged_but_assigned > 0, "the follow-on paths now respect is_rotaed"
        assert unflagged_but_assigned < assigned, "the main loops still gate on it"
