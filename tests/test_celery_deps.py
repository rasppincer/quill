def test_celery_importable():
    import celery
    assert celery.__version__

def test_redis_importable():
    import redis
    assert redis.__version__
