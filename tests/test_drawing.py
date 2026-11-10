"""Pure drawing geometry and unique-entity motion; no desktop interaction."""
import itertools
import math

import pytest

from desktop_world.scene import DrawingSession, assign_targets, sample_strokes, simplify_stroke


def drawing(count=12, bounds=(0, 0, 1000, 700)):
    left, top, _, _ = bounds
    icons = [dict(key=str(i), name=f"icon {i}", home=(left+30+40*(i%5), top+30+50*(i//5)),
                  size=(32, 32)) for i in range(count)]
    return DrawingSession(icons, bounds)


def stroke(session, points, append=True):
    session.begin_stroke(points[0], append=append)
    for point in points[1:]:
        session.add_point(point)
    return session.end_stroke()


def settle(session):
    for _ in range(12*60):
        session.update(1/60)


def test_disconnected_strokes_sample_only_real_ink_and_weight_by_arc_length():
    lines = [[(0, 0), (100, 0)], [(1000, 200), (1300, 200)]]
    assert sample_strokes(lines, 4) == [(50, 0), (1050, 200), (1150, 200), (1250, 200)]
    assert sample_strokes([[], [(0, 0), (0, 0)]], 3) == []
    assert sample_strokes(lines, 0) == []


def test_sampling_closed_path_does_not_duplicate_start_and_end():
    points = sample_strokes([[(0,0),(100,0),(100,100),(0,100),(0,0)]], 4)
    assert len(set(points)) == 4
    assert points == [(50,0),(100,50),(50,100),(0,50)]


def test_simplification_preserves_corners_and_bounds_point_count():
    points = [(i, 0) for i in range(101)] + [(100, i) for i in range(1, 101)]
    assert simplify_stroke(points, .1) == [(0, 0), (100, 0), (100, 100)]
    scribble = [(i, 50 * math.sin(i)) for i in range(2000)]
    reduced = simplify_stroke(scribble, .01, 128)
    assert len(reduced) <= 128
    assert reduced[0] == scribble[0] and reduced[-1] == scribble[-1]


def test_hungarian_assignment_matches_bruteforce_optimum():
    origins = [(0,0),(0,80),(65,10),(100,100)]
    targets = [(90,95),(100,0),(0,100),(10,10)]
    assignment = assign_targets(origins, targets)
    cost = sum(math.dist(origins[i], targets[j]) for i,j in enumerate(assignment))
    optimum = min(sum(math.dist(origins[i], targets[j]) for i,j in enumerate(order))
                  for order in itertools.permutations(range(4)))
    assert sorted(assignment) == list(range(4))
    assert cost == pytest.approx(optimum)


def test_large_assignment_remains_bijective_and_avoids_trivial_crossings():
    origins = [(i * 2, (i%7)*40) for i in range(300)]
    targets = list(reversed(origins))
    assignment = assign_targets(origins, targets)
    assert sorted(assignment) == list(range(300))
    assert all(origins[i] == targets[j] for i,j in enumerate(assignment))


@pytest.mark.parametrize("count", [0, 1, 2, 3, 72])
@pytest.mark.parametrize("name", ["heart", "star", "circle"])
def test_presets_keep_unique_native_actors_inside_bounds(count, name):
    session = drawing(count)
    original = [(id(a), a.key, a.home, a.size) for a in session.actors]
    assert session.preset(name)
    assert len(session.target_points) == count
    assert len({a.target for a in session.actors}) == count
    assert all(0 <= x <= 1000 and 0 <= y <= 700 for x,y in session.strokes[0])
    settle(session)
    assert all(a.pos == a.target and a.state == "arranged" for a in session.actors)
    assert [(id(a), a.key, a.home, a.size) for a in session.actors] == original


def test_default_multiple_strokes_cancel_undo_and_reset():
    session = drawing(6)
    assert stroke(session, [(100,100),(500,100)])
    first = list(session.strokes[0])
    assert stroke(session, [(100,400),(500,400)])
    assert session.stroke_count == 2
    assert all(y in (100,400) for x,y in session.target_points)
    session.begin_stroke((700,500), append=False)
    session.add_point((900,600))
    session.cancel_stroke()
    assert session.stroke_count == 2 and not session.preview
    assert session.undo() and session.strokes == [first]
    settle(session)
    session.reset()
    assert not session.strokes and not session.target_points
    settle(session)
    assert all(a.pos == a.home and a.state == "home" for a in session.actors)
    assert not session.undo()


def test_short_invalid_replacement_does_not_destroy_committed_strokes():
    session = drawing()
    session.preset("circle")
    original = [list(line) for line in session.strokes]
    session.begin_stroke((100,100), append=False)
    assert not session.add_point((100,100))
    assert not session.add_point((float("nan"),100))
    assert not session.end_stroke()
    assert session.strokes == original
    assert not session.begin_stroke((float("inf"),0))
    assert not session.preset("unknown")
    assert session.strokes == original


def test_points_clamp_to_negative_origin_workarea_and_capacity_is_bounded():
    session = drawing(1, (-1000, -700, 0, 0))
    assert stroke(session, [(-2000,-800),(100,100)])
    assert session.strokes == [[(-1000,-700),(0,0)]]
    for index in range(15):
        assert stroke(session, [(-950,-600+index*5),(-500,-600+index*5)])
    assert session.stroke_count == 16
    assert not stroke(session, [(-700,-500),(-100,-500)])
    assert session.stroke_count == 16
    session.begin_stroke((-500,-350))
    for index in range(3000):
        session.add_point((-500 + 200*math.cos(index), -350 + 200*math.sin(index)))
        assert len(session.preview) <= session.MAX_POINTS*2
    assert sum(len(line) for line in session.strokes) <= 16*512


def test_motion_is_monotonic_smooth_and_cannot_overshoot():
    session = drawing(1)
    stroke(session, [(700,500),(900,500)])
    actor = session.actors[0]
    previous = math.dist(actor.pos, actor.target)
    speeds = []
    for _ in range(10*60):
        session.update(1/60)
        current = math.dist(actor.pos, actor.target)
        assert current <= previous + 1e-8
        previous = current
        speeds.append(actor.speed)
    assert actor.pos == actor.target
    assert 0 < speeds[0] < max(speeds) and speeds[-1] == 0
    assert session.total_time == pytest.approx(10)
