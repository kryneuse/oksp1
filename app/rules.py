from datetime import timedelta

TRANSITIONS = {"new": {"in_progress"}, "in_progress": {"closed"}, "closed": set()}

def transition_allowed(old, new):
    return new in TRANSITIONS.get(old, set())

def reaction(created, first_staff, now, norm_minutes):
    elapsed = ((first_staff or now) - created).total_seconds()
    return {"reaction_seconds": elapsed if first_staff else None,
            "sla_breached": elapsed > norm_minutes * 60}
