from job_crawler.relevance import annotate, score_job


def _job(**kw):
    base = {
        "title": "Data Engineer",
        "category": "Data Engineer",
        "tags": '["Python","SQL","Airflow"]',
        "skills": '["Python","SQL","Data Engineer"]',
        "level": "junior",
        "exp_min": 1.0,
    }
    base.update(kw)
    return base


def test_data_engineer_job_scores_high():
    score, matched = score_job(_job())
    assert score >= 80
    assert "Data Engineer" in matched
    assert "Python" in matched


def test_fullstack_job_scores_high():
    score, matched = score_job(_job(
        title="Fullstack Developer (React/Node.js)",
        category="Fullstack Developer",
        tags='["React","Node.js","TypeScript","Docker"]',
        skills='["React","Node.js","TypeScript","Fullstack","Docker"]',
        level="middle",
    ))
    assert score >= 70
    assert "React" in matched and "Node.js" in matched


def test_unrelated_job_scores_low():
    score, matched = score_job(_job(
        title="Senior Java Developer",
        category="Backend Developer",
        tags='["Java","Spring"]',
        skills='["Java","Spring","Backend"]',
        level="senior",
    ))
    assert score < 40
    assert "Java" in matched


def test_level_fit_rewards_junior_over_manager():
    junior = score_job(_job(level="junior"))[0]
    manager = score_job(_job(title="Data Engineering Manager",
                             level="manager"))[0]
    assert junior > manager


def test_score_bounds_and_minimal_job():
    score, _ = score_job({"title": "Tuyển kế toán"})
    assert score == 0
    score, _ = score_job({"title": "Senior Data Engineer Big Data ETL Kafka "
                                   "Spark Airflow Python SQL Docker AWS GCP",
                           "category": "Data Engineer"})
    assert 0 <= score <= 100


def test_annotate_sets_fields():
    j = annotate({"title": "Data Engineer", "category": "Data Engineer"})
    assert isinstance(j["relevance"], int)
    assert j["matched"].startswith("[")  # JSON array
