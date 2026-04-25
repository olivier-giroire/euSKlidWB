import math

def add(a,b): return (a[0]+b[0], a[1]+b[1])
def sub(a,b): return (a[0]-b[0], a[1]-b[1])
def scale(v,s): return (v[0]*s, v[1]*s)
def dot(a,b): return a[0]*b[0] + a[1]*b[1]
def perp(v): return (-v[1], v[0])
def length(v): return math.sqrt(v[0]*v[0] + v[1]*v[1])

def normalize(v):
    l = length(v)
    return (0.0, 0.0) if l == 0 else (v[0]/l, v[1]/l)

def dist2(a,b):
    dx = a[0]-b[0]
    dy = a[1]-b[1]
    return math.sqrt(dx*dx + dy*dy)

def line_from_2pts(p1,p2):
    d = sub(p2,p1)
    if length(d) <= 1e-12:
        return None
    return (p1, normalize(d))

def parallel_line(origin, direction, offset):
    n = normalize(perp(direction))
    return add(origin, scale(n, offset)), direction

def visible_segment_for_line(origin, direction, half_len=1000.0):
    return add(origin, scale(direction, -half_len)), add(origin, scale(direction, half_len))

def point_to_line_distance(point, origin, direction):
    px,py = point
    ox,oy = origin
    dx,dy = direction
    nx,ny = -dy,dx
    return abs((px-ox)*nx + (py-oy)*ny)

def circle_from_3pts(p1,p2,p3):
    x1,y1=p1; x2,y2=p2; x3,y3=p3
    d = 2*(x1*(y2-y3)+x2*(y3-y1)+x3*(y1-y2))
    if abs(d) < 1e-12:
        return None
    ux = ((x1*x1+y1*y1)*(y2-y3)+(x2*x2+y2*y2)*(y3-y1)+(x3*x3+y3*y3)*(y1-y2))/d
    uy = ((x1*x1+y1*y1)*(x3-x2)+(x2*x2+y2*y2)*(x1-x3)+(x3*x3+y3*y3)*(x2-x1))/d
    c = (ux, uy)
    return c, dist2(c, p1)

def circles_from_2pts_radius(p1,p2,r):
    d = dist2(p1,p2)
    if d <= 1e-12 or d > 2*r + 1e-12:
        return []
    m = ((p1[0]+p2[0])*0.5, (p1[1]+p2[1])*0.5)
    n = normalize(perp(sub(p2,p1)))
    h_sq = r*r - (d*0.5)*(d*0.5)
    if h_sq < 0 and h_sq > -1e-9:
        h_sq = 0
    if h_sq < 0:
        return []
    h = math.sqrt(h_sq)
    c1 = add(m, scale(n, h))
    c2 = add(m, scale(n, -h))
    return [c1] if dist2(c1,c2) < 1e-9 else [c1,c2]

def intersect_lines(o1, d1, o2, d2):
    x1,y1 = o1
    x2,y2 = o2
    a1,b1 = d1
    a2,b2 = d2
    det = a1*b2 - b1*a2
    if abs(det) < 1e-12:
        return None
    dx = x2 - x1
    dy = y2 - y1
    t = (dx*b2 - dy*a2) / det
    return (x1 + t*a1, y1 + t*b1)

def tangent_centers_two_lines_radius(line1, line2, radius):
    centers = []
    for s1 in (+1.0, -1.0):
        o1,d1 = parallel_line(line1[0], line1[1], s1*radius)
        for s2 in (+1.0, -1.0):
            o2,d2 = parallel_line(line2[0], line2[1], s2*radius)
            p = intersect_lines(o1,d1,o2,d2)
            if p is None:
                continue
            duplicate = False
            for q in centers:
                if dist2(p,q) < 1e-7:
                    duplicate = True
                    break
            if not duplicate:
                centers.append(p)
    return centers

def line_circle_intersections(line_origin, line_dir, circle_center, circle_radius):
    ox, oy = line_origin
    dx, dy = normalize(line_dir)
    cx, cy = circle_center
    fx = ox - cx
    fy = oy - cy
    b = 2.0 * (fx*dx + fy*dy)
    c = fx*fx + fy*fy - circle_radius*circle_radius
    disc = b*b - 4.0*c
    if disc < -1e-12:
        return []
    if disc < 0:
        disc = 0.0
    s = math.sqrt(disc)
    t1 = (-b - s) / 2.0
    t2 = (-b + s) / 2.0
    pts = [(ox + t1*dx, oy + t1*dy)]
    if abs(t2 - t1) > 1e-9:
        pts.append((ox + t2*dx, oy + t2*dy))
    return pts

def circle_circle_intersections(c1, r1, c2, r2):
    x0,y0 = c1
    x1,y1 = c2
    dx = x1-x0
    dy = y1-y0
    d = math.sqrt(dx*dx + dy*dy)
    if d < 1e-12:
        return []
    if d > r1 + r2 + 1e-12:
        return []
    if d < abs(r1 - r2) - 1e-12:
        return []
    a = (r1*r1 - r2*r2 + d*d) / (2*d)
    h_sq = r1*r1 - a*a
    if h_sq < -1e-12:
        return []
    if h_sq < 0:
        h_sq = 0.0
    h = math.sqrt(h_sq)
    xm = x0 + a*dx/d
    ym = y0 + a*dy/d
    rx = -dy * (h/d)
    ry = dx * (h/d)
    p1 = (xm + rx, ym + ry)
    if h < 1e-9:
        return [p1]
    p2 = (xm - rx, ym - ry)
    return [p1, p2]

def unique_points(points, tol=1e-7):
    out = []
    for p in points:
        dup = False
        for q in out:
            if dist2(p, q) < tol:
                dup = True
                break
        if not dup:
            out.append(p)
    return out



def circles_from_2pts_1tangent_line(p1, p2, line_origin, line_dir):
    mid = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
    chord = sub(p2, p1)
    if length(chord) <= 1e-12:
        return []

    bis_dir = normalize(perp(chord))

    def center_at(t):
        return add(mid, scale(bis_dir, t))

    def f(t):
        c = center_at(t)
        return point_to_line_distance(c, line_origin, line_dir) - dist2(c, p1)

    roots = []
    samples = []
    extent = max(1000.0, dist2(p1, p2) * 10.0)
    n = 400

    for i in range(n + 1):
        t = -extent + 2.0 * extent * i / n
        samples.append((t, f(t)))

    for i in range(n):
        t1, y1 = samples[i]
        t2, y2 = samples[i + 1]

        if abs(y1) < 1e-8:
            roots.append(t1)

        if y1 * y2 < 0:
            a, b = t1, t2
            fa, fb = y1, y2
            for _ in range(60):
                m = 0.5 * (a + b)
                fm = f(m)
                if abs(fm) < 1e-10:
                    a = b = m
                    break
                if fa * fm <= 0:
                    b, fb = m, fm
                else:
                    a, fa = m, fm
            roots.append(0.5 * (a + b))

    centers = [center_at(t) for t in roots]
    centers = unique_points(centers)

    return [
        {"center": c, "radius": dist2(c, p1), "mode": "2pts-1tg-line"}
        for c in centers
        if dist2(c, p1) > 1e-9
    ]


def circles_from_2pts_1tangent_circle(p1, p2, ref_center, ref_radius):
    mid = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
    chord = sub(p2, p1)
    if length(chord) <= 1e-12:
        return []

    bis_dir = normalize(perp(chord))

    def center_at(t):
        return add(mid, scale(bis_dir, t))

    def r_of_t(t):
        c = center_at(t)
        return dist2(c, p1)

    def d_of_t(t):
        c = center_at(t)
        return dist2(c, ref_center)

    def f_ext(t):
        return d_of_t(t) - (ref_radius + r_of_t(t))

    def f_int(t):
        return d_of_t(t) - abs(ref_radius - r_of_t(t))

    def solve_roots(fn):
        roots = []
        samples = []
        extent = max(1000.0, dist2(p1, p2) * 10.0, ref_radius * 5.0)
        n = 500
        for i in range(n + 1):
            t = -extent + 2.0 * extent * i / n
            samples.append((t, fn(t)))
        for i in range(n):
            t1, y1 = samples[i]
            t2, y2 = samples[i + 1]
            if abs(y1) < 1e-8:
                roots.append(t1)
            if y1 * y2 < 0:
                a, b = t1, t2
                fa, fb = y1, y2
                for _ in range(70):
                    m = 0.5 * (a + b)
                    fm = fn(m)
                    if abs(fm) < 1e-10:
                        a = b = m
                        break
                    if fa * fm <= 0:
                        b, fb = m, fm
                    else:
                        a, fa = m, fm
                roots.append(0.5 * (a + b))
        return roots

    roots = solve_roots(f_ext) + solve_roots(f_int)
    centers = unique_points([center_at(t) for t in roots])
    out = []
    for c in centers:
        r = dist2(c, p1)
        if r > 1e-9:
            out.append({'center': c, 'radius': r, 'mode': '2pts-1tg-circle'})
    return out


def project_point_on_line(point, origin, direction):
    d = normalize(direction)
    op = sub(point, origin)
    t = dot(op, d)
    return add(origin, scale(d, t))

def lines_through_point_tangent_circle(point, center, radius):
    px, py = point
    cx, cy = center
    vx = px - cx
    vy = py - cy
    dd = vx * vx + vy * vy
    rr = radius * radius

    if dd < rr - 1e-12:
        return []
    if dd <= 1e-12:
        return []

    d = math.sqrt(dd)

    if abs(d - radius) < 1e-9:
        dx, dy = normalize(perp((vx, vy)))
        return [{"origin": point, "direction": (dx, dy), "mode": "point-tg-circle"}]

    a = rr / dd
    b = radius * math.sqrt(dd - rr) / dd

    tx1 = cx + a * vx - b * vy
    ty1 = cy + a * vy + b * vx
    tx2 = cx + a * vx + b * vy
    ty2 = cy + a * vy - b * vx

    d1 = normalize((tx1 - px, ty1 - py))
    d2v = normalize((tx2 - px, ty2 - py))

    out = [{"origin": point, "direction": d1, "mode": "point-tg-circle"}]
    if dist2((tx1, ty1), (tx2, ty2)) > 1e-9:
        out.append({"origin": point, "direction": d2v, "mode": "point-tg-circle"})
    return out

def parallel_lines_tangent_circle(direction, center, radius):
    d = normalize(direction)
    if length(d) <= 1e-12:
        return []
    n = normalize(perp(d))
    out = []
    for s in (+1.0, -1.0):
        origin = add(center, scale(n, s * radius))
        out.append({"origin": origin, "direction": d, "mode": "parallel-tg-circle"})
    return out

def parallel_ref_tangent_circle(ref_origin, ref_direction, center, radius):
    return parallel_lines_tangent_circle(ref_direction, center, radius)
