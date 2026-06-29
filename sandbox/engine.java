import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.stream.*;

/**
 * Standalone Java engine for the himark opcode IR. Zero external dependencies.
 *
 * Single-file launch (Java 11+):
 *   java sandbox/engine.java
 *
 * stdin:  {"pipeline": [[step, ...], ...], "target": "..."}
 * stdout: {"result": "..."} | {"error": "..."}
 *
 * See docs/ENGINE.md for the full design.
 */
class engine {

    // ── Opcode constants ──────────────────────────────────────────────────────

    static final int LIT = 0, ANCHOR = 1, CHAR = 2, GROUP = 3, BACK_REF = 4,
                     COUNT_REF = 5, STAGE_REF = 6, VALUE_RANGE = 7, DYN_RANGE = 8,
                     COMPLEMENT = 10, SEQ_GROUP = 11;

    // ── Minimal JSON ──────────────────────────────────────────────────────────
    // Values: String, Double, Boolean, null, List<Object>, Map<String,Object>

    static Object parseJson(String src) { return parseValue(src, new int[]{0}); }

    static void skipWs(String s, int[] p) {
        while (p[0] < s.length() && s.charAt(p[0]) <= ' ') p[0]++;
    }

    static Object parseValue(String s, int[] p) {
        skipWs(s, p);
        if (p[0] >= s.length()) return null;
        char c = s.charAt(p[0]);
        if (c == '"') return parseString(s, p);
        if (c == '[') return parseArray(s, p);
        if (c == '{') return parseObject(s, p);
        if (c == 't') { p[0] += 4; return Boolean.TRUE; }
        if (c == 'f') { p[0] += 5; return Boolean.FALSE; }
        if (c == 'n') { p[0] += 4; return null; }
        return parseNumber(s, p);
    }

    static String parseString(String s, int[] p) {
        p[0]++; // skip "
        var sb = new StringBuilder();
        while (p[0] < s.length()) {
            char c = s.charAt(p[0]++);
            if (c == '"') break;
            if (c != '\\') { sb.append(c); continue; }
            char e = s.charAt(p[0]++);
            switch (e) {
                case '"': sb.append('"'); break;
                case '\\': sb.append('\\'); break;
                case '/':  sb.append('/');  break;
                case 'b':  sb.append('\b'); break;
                case 'f':  sb.append('\f'); break;
                case 'n':  sb.append('\n'); break;
                case 'r':  sb.append('\r'); break;
                case 't':  sb.append('\t'); break;
                case 'u':
                    sb.append((char) Integer.parseInt(s.substring(p[0], p[0] + 4), 16));
                    p[0] += 4;
                    break;
                default: sb.append(e);
            }
        }
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    static List<Object> parseArray(String s, int[] p) {
        p[0]++; // skip [
        var list = new ArrayList<Object>();
        skipWs(s, p);
        if (p[0] < s.length() && s.charAt(p[0]) == ']') { p[0]++; return list; }
        while (true) {
            list.add(parseValue(s, p));
            skipWs(s, p);
            char c = p[0] < s.length() ? s.charAt(p[0]++) : ']';
            if (c == ']') break;
        }
        return list;
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> parseObject(String s, int[] p) {
        p[0]++; // skip {
        var map = new LinkedHashMap<String, Object>();
        skipWs(s, p);
        if (p[0] < s.length() && s.charAt(p[0]) == '}') { p[0]++; return map; }
        while (true) {
            skipWs(s, p);
            String key = parseString(s, p);
            skipWs(s, p);
            p[0]++; // skip :
            map.put(key, parseValue(s, p));
            skipWs(s, p);
            char c = p[0] < s.length() ? s.charAt(p[0]++) : '}';
            if (c == '}') break;
        }
        return map;
    }

    static double parseNumber(String s, int[] p) {
        int start = p[0];
        if (p[0] < s.length() && s.charAt(p[0]) == '-') p[0]++;
        while (p[0] < s.length() && Character.isDigit(s.charAt(p[0]))) p[0]++;
        if (p[0] < s.length() && s.charAt(p[0]) == '.') {
            p[0]++;
            while (p[0] < s.length() && Character.isDigit(s.charAt(p[0]))) p[0]++;
        }
        if (p[0] < s.length() && (s.charAt(p[0]) == 'e' || s.charAt(p[0]) == 'E')) {
            p[0]++;
            if (p[0] < s.length() && (s.charAt(p[0]) == '+' || s.charAt(p[0]) == '-')) p[0]++;
            while (p[0] < s.length() && Character.isDigit(s.charAt(p[0]))) p[0]++;
        }
        return Double.parseDouble(s.substring(start, p[0]));
    }

    static String jsonStr(String s) {
        var sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':  sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n");  break;
                case '\r': sb.append("\\r");  break;
                case '\t': sb.append("\\t");  break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.append('"').toString();
    }

    // ── Reps ──────────────────────────────────────────────────────────────────

    static class Reps {
        int min = 1;
        Integer max = 1;
        Set<Integer> allowed = null;
        Integer countRef = null;

        static Reps exact(int n) {
            var r = new Reps();
            r.min = n;
            r.max = n;
            return r;
        }

        boolean accepts(int k) {
            if (allowed != null) return allowed.contains(k);
            return k >= min && (max == null || k <= max);
        }
    }

    static int asInt(Object v) { return (int) ((Double) v).doubleValue(); }

    @SuppressWarnings("unchecked")
    static Reps parseReps(Object v) {
        if (!(v instanceof List)) return Reps.exact(1);
        var arr = (List<Object>) v;
        if (arr.isEmpty()) return Reps.exact(1);
        if ("#".equals(arr.get(0))) {
            var r = new Reps();
            r.min = 0; r.max = null; r.countRef = asInt(arr.get(1));
            return r;
        }
        if ("=".equals(arr.get(0))) {
            var vals = (List<Object>) arr.get(1);
            Set<Integer> set = new HashSet<>();
            int lo = Integer.MAX_VALUE, hi = Integer.MIN_VALUE;
            for (var x : vals) {
                int k = asInt(x); set.add(k);
                lo = Math.min(lo, k); hi = Math.max(hi, k);
            }
            var r = new Reps();
            r.min = lo; r.max = hi; r.allowed = set;
            return r;
        }
        int lo = asInt(arr.get(0));
        int hiRaw = asInt(arr.get(1));
        var r = new Reps();
        r.min = lo; r.max = hiRaw == -1 ? null : hiRaw;
        return r;
    }

    // ── Capture ───────────────────────────────────────────────────────────────

    static class Capture {
        String text = "";
        int spanStart, spanEnd;
        List<String> reps;
        List<Capture> subs;
        int count; // -1 means use reps.size()

        Capture(int spanStart, int spanEnd, List<String> reps, List<Capture> subs, int count) {
            this.spanStart = spanStart; this.spanEnd = spanEnd;
            this.reps = reps; this.subs = subs; this.count = count;
        }

        int repCount() { return count >= 0 ? count : reps.size(); }
    }

    // ── HMatch ────────────────────────────────────────────────────────────────

    static class HMatch {
        String text;
        int start, end;
        List<Capture> captures;

        HMatch(String text, int start, int end, List<Capture> captures) {
            this.text = text; this.start = start; this.end = end;
            this.captures = captures;
        }

        Capture captureAt(int[] path) {
            List<Capture> caps = captures;
            Capture cap = null;
            for (int idx : path) {
                if (idx >= caps.size()) return null;
                cap = caps.get(idx);
                caps = cap.subs;
            }
            return cap;
        }
    }

    // ── Alphabet ──────────────────────────────────────────────────────────────

    static abstract class Alphabet {
        abstract boolean containsChar(char ch);
        abstract Double value(String s);
    }

    static class RangeAlphabet extends Alphabet {
        int lo, hi;
        RangeAlphabet(int lo, int hi) { this.lo = lo; this.hi = hi; }

        boolean containsChar(char ch) { return lo <= ch && ch <= hi; }

        Double value(String s) {
            double v = 0;
            int base = hi - lo + 1;
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                if (c < lo || c > hi) return null;
                v = v * base + (c - lo);
            }
            return v;
        }
    }

    static class GroupAlphabet extends Alphabet {
        List<Map.Entry<String, Integer>> entries; // sorted longest-first
        int base;

        GroupAlphabet(List<List<Object>> groups) {
            var index = new LinkedHashMap<String, Integer>();
            base = groups.size();
            for (int i = 0; i < groups.size(); i++)
                for (Object m : groups.get(i))
                    index.put((String) m, i);
            entries = new ArrayList<>(index.entrySet());
            entries.sort((a, b) -> b.getKey().length() - a.getKey().length());
        }

        boolean containsChar(char ch) {
            String s = String.valueOf(ch);
            for (var e : entries) if (e.getKey().equals(s)) return true;
            return false;
        }

        Double value(String s) {
            double v = 0;
            int i = 0;
            while (i < s.length()) {
                boolean found = false;
                for (var e : entries) {
                    if (s.startsWith(e.getKey(), i)) {
                        v = v * base + e.getValue();
                        i += e.getKey().length();
                        found = true;
                        break;
                    }
                }
                if (!found) return null;
            }
            return v;
        }
    }

    @SuppressWarnings("unchecked")
    static Alphabet parseAlphabet(Object v) {
        var arr = (List<Object>) v;
        if ("range".equals(arr.get(0)))
            return new RangeAlphabet(asInt(arr.get(1)), asInt(arr.get(2)));
        var grpsRaw = (List<Object>) arr.get(1);
        List<List<Object>> grps = new ArrayList<>();
        for (var g : grpsRaw) grps.add((List<Object>) g);
        return new GroupAlphabet(grps);
    }

    // ── Exclusions ────────────────────────────────────────────────────────────

    static class Exclusions {
        Set<Character> singles;
        List<char[]> ranges; // each is {lo, hi}
        List<String> literals;

        Exclusions(Set<Character> singles, List<char[]> ranges, List<String> literals) {
            this.singles = singles; this.ranges = ranges; this.literals = literals;
        }

        boolean excludesAt(String text, int pos) {
            if (pos >= text.length()) return false;
            char ch = text.charAt(pos);
            if (singles.contains(ch)) return true;
            for (var r : ranges) if (r[0] <= ch && ch <= r[1]) return true;
            for (var lit : literals) if (text.startsWith(lit, pos)) return true;
            return false;
        }
    }

    @SuppressWarnings("unchecked")
    static Exclusions parseExcl(Object v) {
        if (!(v instanceof List)) return null;
        var arr = (List<Object>) v;
        if (arr.isEmpty()) return null;
        Set<Character> singles = new HashSet<>();
        for (var x : (List<Object>) arr.get(0))
            if (x instanceof String s && !s.isEmpty()) singles.add(s.charAt(0));
        List<char[]> ranges = new ArrayList<>();
        for (var x : (List<Object>) arr.get(1)) {
            var pair = (List<Object>) x;
            ranges.add(new char[]{((String) pair.get(0)).charAt(0), ((String) pair.get(1)).charAt(0)});
        }
        List<String> literals = new ArrayList<>();
        for (var x : (List<Object>) arr.get(2)) literals.add((String) x);
        if (singles.isEmpty() && ranges.isEmpty() && literals.isEmpty()) return null;
        return new Exclusions(singles, ranges, literals);
    }

    // ── Matchers ──────────────────────────────────────────────────────────────

    static abstract class Matcher {
        abstract Integer matchOne(String text, int pos);

        boolean accepts(String s) {
            Integer end = matchOne(s, 0);
            return end != null && end == s.length();
        }

        Integer equalUnit(String text, int pos, String first) {
            return text.startsWith(first, pos) ? pos + first.length() : null;
        }
    }

    static class CharMatcher extends Matcher {
        int lo, hi;
        Exclusions excl;

        CharMatcher(int lo, int hi, Exclusions excl) { this.lo = lo; this.hi = hi; this.excl = excl; }

        Integer matchOne(String text, int pos) {
            if (pos >= text.length()) return null;
            char ch = text.charAt(pos);
            if (ch < lo || ch > hi) return null;
            if (excl != null && excl.excludesAt(text, pos)) return null;
            return pos + 1;
        }
    }

    static class GroupMatcher extends Matcher {
        // (member, group_index) pairs sorted longest-first
        List<Object[]> members;
        Set<String> acceptSet;

        @SuppressWarnings("unchecked")
        GroupMatcher(List<List<Object>> groups) {
            members = new ArrayList<>();
            for (int i = 0; i < groups.size(); i++)
                for (Object m : groups.get(i))
                    if (!((String) m).isEmpty())
                        members.add(new Object[]{(String) m, i});
            members.sort((a, b) -> ((String) b[0]).length() - ((String) a[0]).length());
            acceptSet = new HashSet<>();
            for (var m : members) acceptSet.add((String) m[0]);
        }

        Integer matchOne(String text, int pos) {
            for (var m : members)
                if (text.startsWith((String) m[0], pos))
                    return pos + ((String) m[0]).length();
            return null;
        }

        boolean accepts(String s) { return acceptSet.contains(s); }

        Integer equalUnit(String text, int pos, String first) {
            List<Integer> seq = new ArrayList<>();
            int i = 0;
            while (i < first.length()) {
                boolean found = false;
                for (var m : members) {
                    if (first.startsWith((String) m[0], i)) {
                        seq.add((Integer) m[1]);
                        i += ((String) m[0]).length();
                        found = true;
                        break;
                    }
                }
                if (!found) return null;
            }
            int cur = pos;
            for (int gidx : seq) {
                boolean found = false;
                for (var m : members) {
                    if ((int) m[1] == gidx && text.startsWith((String) m[0], cur)) {
                        cur += ((String) m[0]).length();
                        found = true;
                        break;
                    }
                }
                if (!found) return null;
            }
            return cur;
        }
    }

    static class ComplementMatcher extends Matcher {
        List<List<String>> innerGroups;

        ComplementMatcher(List<List<String>> innerGroups) { this.innerGroups = innerGroups; }

        Integer matchOne(String text, int pos) {
            if (pos >= text.length()) return null;
            for (var grp : innerGroups)
                for (var m : grp)
                    if (!m.isEmpty() && text.startsWith(m, pos)) return null;
            return pos + 1;
        }

        Integer equalUnit(String text, int pos, String first) { return matchOne(text, pos); }
    }

    static class ValueMatcher extends Matcher {
        Alphabet alph;
        Double loVal, hiVal;
        int wmin;
        Integer wmax;
        Exclusions excl;

        ValueMatcher(Alphabet alph, Double loVal, Double hiVal, int wmin, Integer wmax, Exclusions excl) {
            this.alph = alph; this.loVal = loVal; this.hiVal = hiVal;
            this.wmin = wmin; this.wmax = wmax; this.excl = excl;
        }

        Integer matchOne(String text, int pos) {
            int end = pos;
            while (end < text.length() && alph.containsChar(text.charAt(end))) end++;
            int avail = end - pos;
            int top = wmax != null ? Math.min(wmax, avail) : avail;
            if (top < wmin) return null;
            for (int w = top; w >= wmin; w--) {
                String candidate = text.substring(pos, pos + w);
                if (excl != null) {
                    if (excl.literals.contains(candidate)) continue;
                    if (w == 1 && excl.excludesAt(text, pos)) continue;
                }
                Double val = alph.value(candidate);
                if (val == null) continue;
                if (loVal != null && val < loVal) continue;
                if (hiVal != null && val > hiVal) continue;
                return pos + w;
            }
            return null;
        }
    }

    // ── RefDesc (for DYN_RANGE endpoints) ────────────────────────────────────

    static class RefDesc {
        String kind; // "back", "count", "stage"
        int idx;
        int[] path;

        RefDesc(String kind, int idx, int[] path) { this.kind = kind; this.idx = idx; this.path = path; }
    }

    @SuppressWarnings("unchecked")
    static RefDesc parseRefDesc(Object v) {
        if (!(v instanceof List)) return null;
        var arr = (List<Object>) v;
        String kind = (String) arr.get(0);
        int idx = asInt(arr.get(1));
        int[] path = {};
        if (arr.size() > 2 && arr.get(2) instanceof List) {
            var pArr = (List<Object>) arr.get(2);
            path = pArr.stream().mapToInt(engine::asInt).toArray();
        }
        return new RefDesc(kind, idx, path);
    }

    // ── Element (prepared VM instruction) ────────────────────────────────────

    static class Element {
        int op;
        // LIT
        String litStr;
        // ANCHOR
        int anchorKind;
        // CHAR
        int charLo, charHi;
        // GROUP
        GroupMatcher groupMatcher;
        // COMPLEMENT
        List<List<String>> complementGroups;
        // BACK_REF / COUNT_REF
        int refIdx;
        // STAGE_REF
        int stageIdx;
        int[] stagePath;
        // VALUE_RANGE / DYN_RANGE
        Alphabet alph;
        Double loVal, hiVal;
        int wmin;
        Integer wmax;
        // DYN_RANGE only
        String loStatic, hiStatic;
        RefDesc loRef, hiRef;
        // SEQ_GROUP
        List<Element> children;
        // common (all reps-bearing opcodes)
        Exclusions excl;
        Reps reps;
    }

    @SuppressWarnings("unchecked")
    static List<Element> prepareElements(Object json) {
        if (!(json instanceof List)) return List.of();
        var arr = (List<Object>) json;
        var out = new ArrayList<Element>();
        for (var elObj : arr) {
            if (!(elObj instanceof List)) continue;
            var el = (List<Object>) elObj;
            if (el.isEmpty()) continue;
            int op = asInt(el.get(0));
            var e = new Element();
            e.op = op;
            switch (op) {
                case LIT:
                    e.litStr = (String) el.get(1);
                    break;
                case ANCHOR:
                    e.anchorKind = asInt(el.get(1));
                    break;
                case CHAR:
                    e.charLo = asInt(el.get(1));
                    e.charHi = asInt(el.get(2));
                    e.excl = parseExcl(el.get(3));
                    e.reps = parseReps(el.get(el.size() - 1));
                    break;
                case GROUP: {
                    var grpsRaw = (List<Object>) el.get(1);
                    List<List<Object>> grps = new ArrayList<>();
                    for (var g : grpsRaw) grps.add((List<Object>) g);
                    e.groupMatcher = new GroupMatcher(grps);
                    e.reps = parseReps(el.get(el.size() - 1));
                    break;
                }
                case BACK_REF:
                case COUNT_REF:
                    e.refIdx = asInt(el.get(1));
                    e.reps = parseReps(el.get(el.size() - 1));
                    break;
                case STAGE_REF:
                    e.stageIdx = asInt(el.get(1));
                    e.stagePath = ((List<Object>) el.get(2)).stream().mapToInt(engine::asInt).toArray();
                    e.reps = parseReps(el.get(el.size() - 1));
                    break;
                case VALUE_RANGE:
                    e.alph = parseAlphabet(el.get(1));
                    e.loVal = el.get(2) instanceof Double ? (Double) el.get(2) : null;
                    e.hiVal = el.get(3) instanceof Double ? (Double) el.get(3) : null;
                    e.wmin = asInt(el.get(4));
                    e.wmax = el.get(5) instanceof Double ? asInt(el.get(5)) : null;
                    e.excl = parseExcl(el.get(6));
                    e.reps = parseReps(el.get(el.size() - 1));
                    break;
                case DYN_RANGE:
                    e.alph = parseAlphabet(el.get(1));
                    e.loStatic = el.get(2) instanceof String ? (String) el.get(2) : null;
                    e.hiStatic = el.get(3) instanceof String ? (String) el.get(3) : null;
                    e.loRef = el.get(4) != null ? parseRefDesc(el.get(4)) : null;
                    e.hiRef = el.get(5) != null ? parseRefDesc(el.get(5)) : null;
                    e.excl = parseExcl(el.get(6));
                    e.reps = parseReps(el.get(el.size() - 1));
                    break;
                case COMPLEMENT: {
                    e.complementGroups = new ArrayList<>();
                    for (var g : (List<Object>) el.get(1)) {
                        List<String> grp = new ArrayList<>();
                        for (var m : (List<Object>) g) grp.add((String) m);
                        e.complementGroups.add(grp);
                    }
                    e.reps = parseReps(el.get(el.size() - 1));
                    break;
                }
                case SEQ_GROUP:
                    e.children = prepareElements(el.get(1));
                    e.reps = parseReps(el.get(el.size() - 1));
                    break;
                default:
                    continue;
            }
            out.add(e);
        }
        return out;
    }

    // ── State ─────────────────────────────────────────────────────────────────

    static class State {
        List<Capture> captures = new ArrayList<>();
        List<HMatch> stages;
        // Back-refs inside a SEQ_GROUP child see only captures[0..rootLen].
        // Integer.MAX_VALUE means "no restriction" (top-level, outside any SEQ_GROUP).
        int rootLen = Integer.MAX_VALUE;

        State(List<HMatch> stages) { this.stages = stages; }
    }

    // ── Resolve helpers ───────────────────────────────────────────────────────

    static int captureLimit(State state) {
        return Math.min(state.rootLen, state.captures.size());
    }

    static String resolveBack(int idx, State state, String text) {
        if (idx >= captureLimit(state)) return null;
        var c = state.captures.get(idx);
        return text.substring(c.spanStart, c.spanEnd);
    }

    static String resolveCount(int idx, State state) {
        if (idx >= captureLimit(state)) return null;
        return String.valueOf(state.captures.get(idx).repCount());
    }

    static String resolveStage(int stageIdx, int[] path, State state) {
        if (stageIdx >= state.stages.size()) return null;
        var m = state.stages.get(stageIdx);
        if (path.length == 0) return m.text;
        var cap = m.captureAt(path);
        return cap == null ? null : cap.text;
    }

    static Reps resolveReps(Reps reps, State state) {
        if (reps.countRef == null) return reps;
        if (reps.countRef >= captureLimit(state)) return null;
        int k = state.captures.get(reps.countRef).repCount();
        return Reps.exact(k);
    }

    static String resolveReferentDesc(RefDesc desc, State state, String text) {
        return switch (desc.kind) {
            case "back"  -> resolveBack(desc.idx, state, text);
            case "count" -> resolveCount(desc.idx, state);
            case "stage" -> resolveStage(desc.idx, desc.path, state);
            default -> null;
        };
    }

    // ── Anchor check ──────────────────────────────────────────────────────────

    static boolean checkAnchor(int kind, String text, int pos) {
        return switch (kind) {
            case 0 -> pos == 0 || text.charAt(pos - 1) == '\n';
            case 1 -> pos == text.length() || text.charAt(pos) == '\n';
            case 2 -> pos == 0;
            default -> pos == text.length();
        };
    }

    // ── Repetition count candidates (greedy-first) ────────────────────────────

    static List<Integer> counts(Reps reps, int built) {
        var ks = new ArrayList<Integer>();
        for (int k = built; k >= 1; k--)
            if (reps.accepts(k)) ks.add(k);
        if (reps.accepts(0)) ks.add(0);
        return ks;
    }

    // ── VM ────────────────────────────────────────────────────────────────────

    static Integer runProgram(List<Element> elements, int idx, String text, int pos, State state) {
        if (idx >= elements.size()) return pos;
        var e = elements.get(idx);

        if (e.op == LIT)
            return text.startsWith(e.litStr, pos)
                ? runProgram(elements, idx + 1, text, pos + e.litStr.length(), state) : null;

        if (e.op == ANCHOR)
            return checkAnchor(e.anchorKind, text, pos)
                ? runProgram(elements, idx + 1, text, pos, state) : null;

        if (e.op == CHAR) {
            Reps r = resolveReps(e.reps, state); if (r == null) return null;
            return runMatcher(new CharMatcher(e.charLo, e.charHi, e.excl), r, elements, idx + 1, state, text, pos);
        }
        if (e.op == GROUP) {
            Reps r = resolveReps(e.reps, state); if (r == null) return null;
            return runMatcher(e.groupMatcher, r, elements, idx + 1, state, text, pos);
        }
        if (e.op == COMPLEMENT) {
            Reps r = resolveReps(e.reps, state); if (r == null) return null;
            return runMatcher(new ComplementMatcher(e.complementGroups), r, elements, idx + 1, state, text, pos);
        }
        if (e.op == BACK_REF) {
            Reps r = resolveReps(e.reps, state); if (r == null) return null;
            return matchReferent(resolveBack(e.refIdx, state, text), r, elements, idx + 1, text, pos, state);
        }
        if (e.op == COUNT_REF) {
            Reps r = resolveReps(e.reps, state); if (r == null) return null;
            return matchReferent(resolveCount(e.refIdx, state), r, elements, idx + 1, text, pos, state);
        }
        if (e.op == STAGE_REF) {
            Reps r = resolveReps(e.reps, state); if (r == null) return null;
            return matchReferent(resolveStage(e.stageIdx, e.stagePath, state), r, elements, idx + 1, text, pos, state);
        }
        if (e.op == VALUE_RANGE) {
            Reps r = resolveReps(e.reps, state); if (r == null) return null;
            return runMatcher(new ValueMatcher(e.alph, e.loVal, e.hiVal, e.wmin, e.wmax, e.excl),
                              r, elements, idx + 1, state, text, pos);
        }
        if (e.op == DYN_RANGE) {
            Reps r = resolveReps(e.reps, state); if (r == null) return null;
            String lower = e.loRef != null ? resolveReferentDesc(e.loRef, state, text) : e.loStatic;
            String upper = e.hiRef != null ? resolveReferentDesc(e.hiRef, state, text) : e.hiStatic;
            if (e.loRef != null && lower == null) return null;
            if (e.hiRef != null && upper == null) return null;
            var vm = buildDynMatcher(e.alph, lower, upper, e.excl);
            if (vm == null) return null;
            return runMatcher(vm, r, elements, idx + 1, state, text, pos);
        }
        if (e.op == SEQ_GROUP) {
            Reps r = resolveReps(e.reps, state); if (r == null) return null;
            return matchSeqGroup(e.children, r, elements, idx + 1, text, pos, state);
        }
        throw new RuntimeException("Unknown opcode: " + e.op);
    }

    static ValueMatcher buildDynMatcher(Alphabet alph, String lower, String upper, Exclusions excl) {
        Double loVal = null, hiVal = null;
        if (lower != null) { loVal = alph.value(lower); if (loVal == null) return null; }
        if (upper != null) { hiVal = alph.value(upper); if (hiVal == null) return null; }
        int wmin;
        Integer wmax;
        if (lower != null && upper != null) {
            wmin = Math.min(lower.length(), upper.length());
            wmax = Math.max(lower.length(), upper.length());
        } else if (lower != null) {
            wmin = lower.length(); wmax = null;
        } else if (upper != null) {
            wmin = 1; wmax = upper.length();
        } else {
            wmin = 1; wmax = null;
        }
        return new ValueMatcher(alph, loVal, hiVal, wmin, wmax, excl);
    }

    static Integer tryZero(Reps reps, List<Element> elements, int nextIdx,
                           State state, String text, int pos) {
        if (!reps.accepts(0)) return null;
        int mark = state.captures.size();
        state.captures.add(new Capture(pos, pos, new ArrayList<>(), new ArrayList<>(), 0));
        Integer result = runProgram(elements, nextIdx, text, pos, state);
        if (result == null) state.captures.subList(mark, state.captures.size()).clear();
        return result;
    }

    static Integer runMatcher(Matcher matcher, Reps reps, List<Element> elements, int nextIdx,
                              State state, String text, int pos) {
        Integer firstEnd = matcher.matchOne(text, pos);
        if (firstEnd == null || firstEnd == pos)
            return tryZero(reps, elements, nextIdx, state, text, pos);

        for (int unitLen = firstEnd - pos; unitLen >= 1; unitLen--) {
            String first = text.substring(pos, pos + unitLen);
            if (!matcher.accepts(first)) continue;

            List<String> repList = new ArrayList<>();
            repList.add(first);
            List<Integer> ends = new ArrayList<>();
            ends.add(pos + unitLen);
            int current = pos + unitLen;

            while (reps.max == null || repList.size() < reps.max) {
                Integer nxt = matcher.equalUnit(text, current, first);
                if (nxt == null || nxt <= current) break;
                repList.add(text.substring(current, nxt));
                ends.add(nxt);
                current = nxt;
            }

            for (int k : counts(reps, repList.size())) {
                int end = k == 0 ? pos : ends.get(k - 1);
                var repsSlice = new ArrayList<>(repList.subList(0, Math.min(k, repList.size())));
                int mark = state.captures.size();
                state.captures.add(new Capture(pos, end, repsSlice, new ArrayList<>(), k));
                Integer result = runProgram(elements, nextIdx, text, end, state);
                if (result != null) return result;
                state.captures.subList(mark, state.captures.size()).clear();
            }
        }
        return tryZero(reps, elements, nextIdx, state, text, pos);
    }

    static Integer matchReferent(String referent, Reps reps, List<Element> elements, int nextIdx,
                                 String text, int pos, State state) {
        if (referent == null) return null;
        if (referent.isEmpty()) {
            int mark = state.captures.size();
            var repsList = new ArrayList<String>();
            for (int i = 0; i < reps.min; i++) repsList.add("");
            state.captures.add(new Capture(pos, pos, repsList, new ArrayList<>(), -1));
            Integer result = runProgram(elements, nextIdx, text, pos, state);
            if (result == null) state.captures.subList(mark, state.captures.size()).clear();
            return result;
        }
        List<Integer> endsList = new ArrayList<>();
        endsList.add(pos);
        int current = pos;
        while ((reps.max == null || (endsList.size() - 1) < reps.max)
               && text.startsWith(referent, current)) {
            current += referent.length();
            endsList.add(current);
        }
        for (int k : counts(reps, endsList.size() - 1)) {
            int end = endsList.get(k);
            var repsList = new ArrayList<String>();
            for (int i = 0; i < k; i++) repsList.add(referent);
            int mark = state.captures.size();
            state.captures.add(new Capture(pos, end, repsList, new ArrayList<>(), -1));
            Integer result = runProgram(elements, nextIdx, text, end, state);
            if (result != null) return result;
            state.captures.subList(mark, state.captures.size()).clear();
        }
        return null;
    }

    static Integer matchSeqGroup(List<Element> children, Reps reps, List<Element> elements, int nextIdx,
                                 String text, int pos, State state) {
        // Mirror Python's _State.root: children see only captures that existed before
        // the outermost SEQ_GROUP started. Nested SEQ_GROUPs leave rootLen unchanged.
        int prevRootLen = state.rootLen;
        if (state.rootLen == Integer.MAX_VALUE) state.rootLen = state.captures.size();

        List<Integer> runEnds = new ArrayList<>();
        List<List<Capture>> runCaps = new ArrayList<>();
        int current = pos;

        while (reps.max == null || runEnds.size() < reps.max) {
            int snapLen = state.captures.size();
            Integer end = runProgram(children, 0, text, current, state);
            if (end != null && end > current) {
                var subCaps = new ArrayList<>(state.captures.subList(snapLen, state.captures.size()));
                state.captures.subList(snapLen, state.captures.size()).clear();
                runEnds.add(end);
                runCaps.add(subCaps);
                current = end;
            } else {
                state.captures.subList(snapLen, state.captures.size()).clear();
                break;
            }
        }

        state.rootLen = prevRootLen; // restore before trying continuations

        for (int k : counts(reps, runEnds.size())) {
            int end = k == 0 ? pos : runEnds.get(k - 1);
            var repTexts = new ArrayList<String>();
            for (int i = 0; i < k; i++) {
                int start = i == 0 ? pos : runEnds.get(i - 1);
                repTexts.add(text.substring(start, runEnds.get(i)));
            }
            var subs = new ArrayList<Capture>();
            for (int i = 0; i < k; i++) subs.addAll(runCaps.get(i));
            int mark = state.captures.size();
            var cap = new Capture(pos, end, repTexts, subs, -1);
            cap.text = text.substring(pos, end);
            state.captures.add(cap);
            Integer result = runProgram(elements, nextIdx, text, end, state);
            if (result != null) return result;
            state.captures.subList(mark, state.captures.size()).clear();
        }
        return null;
    }

    // ── Finalize match ────────────────────────────────────────────────────────

    static void finalizeCapture(Capture cap, String text, int start) {
        if (cap.count >= 0)
            while (cap.reps.size() > cap.count) cap.reps.remove(cap.reps.size() - 1);
        cap.text = text.substring(cap.spanStart, cap.spanEnd);
        cap.spanStart -= start;
        cap.spanEnd -= start;
        for (var sub : cap.subs) finalizeCapture(sub, text, start);
    }

    static HMatch finalize(String text, int start, int end, State state) {
        for (var cap : state.captures) finalizeCapture(cap, text, start);
        return new HMatch(text.substring(start, end), start, end, new ArrayList<>(state.captures));
    }

    // ── findMatches ───────────────────────────────────────────────────────────

    static List<HMatch> findMatches(List<Element> elements, String text, List<HMatch> stages) {
        var matches = new ArrayList<HMatch>();
        int pos = 0, n = text.length();
        while (pos < n) {
            var state = new State(stages);
            Integer end = runProgram(elements, 0, text, pos, state);
            if (end != null && end > pos) {
                matches.add(finalize(text, pos, end, state));
                pos = end;
            } else {
                pos++;
            }
        }
        return matches;
    }

    // ── Template ──────────────────────────────────────────────────────────────

    static class Template {
        List<Object> parts; // String literals | Map<String,Object> moustache exprs
        boolean fixedPoint;

        Template(List<Object> parts, boolean fixedPoint) { this.parts = parts; this.fixedPoint = fixedPoint; }
    }

    @SuppressWarnings("unchecked")
    static String evalExpr(Object d, String current, List<HMatch> stages) {
        var m = (Map<String, Object>) d;
        if (m.containsKey("lit")) return (String) m.get("lit");
        if (m.containsKey("cur")) return current;
        if (m.containsKey("ref")) {
            var ref = (List<Object>) m.get("ref");
            Integer stageIdx = ref.get(0) instanceof Double ? asInt(ref.get(0)) : null;
            boolean isCount = Boolean.TRUE.equals(ref.get(1));
            Object pathObj = ref.get(2);
            int pipeIdx = stageIdx != null ? stageIdx : stages.size() - 1;
            if (pipeIdx < 0 || pipeIdx >= stages.size())
                throw new RuntimeException("Moustache stage " + pipeIdx + " out of range");
            var sm = stages.get(pipeIdx);
            if (pathObj == null) return sm.text;
            int[] path = ((List<Object>) pathObj).stream().mapToInt(engine::asInt).toArray();
            var cap = sm.captureAt(path);
            if (cap == null) throw new RuntimeException("Moustache capture out of range");
            return isCount ? String.valueOf(cap.reps.size()) : cap.text;
        }
        if (m.containsKey("cat")) {
            var sb = new StringBuilder();
            for (var p : (List<Object>) m.get("cat")) sb.append(evalExpr(p, current, stages));
            return sb.toString();
        }
        if (m.containsKey("filter")) {
            String name = (String) m.get("filter");
            String val = evalExpr(m.get("src"), current, stages);
            return switch (name) {
                case "trim"   -> val.strip();
                case "indent" -> val.isEmpty() ? "" : "\t" + val.replace("\n", "\n\t");
                default -> throw new RuntimeException("Unknown template filter: '" + name + "'");
            };
        }
        throw new RuntimeException("Unknown expression: " + d);
    }

    // Returns Object[]{String full, List<int[]> spans | null}
    static Object[] renderTemplate(Template tmpl, String current, List<HMatch> stages) {
        var sb = new StringBuilder();
        List<int[]> spans = new ArrayList<>();
        for (var part : tmpl.parts) {
            if (part instanceof String s) {
                sb.append(s);
            } else {
                String val = evalExpr(part, current, stages);
                int start = sb.length();
                sb.append(val);
                spans.add(new int[]{start, sb.length()});
            }
        }
        return new Object[]{sb.toString(), spans.isEmpty() ? null : spans};
    }

    @SuppressWarnings("unchecked")
    static Template templateFromJson(Map<String, Object> d) {
        boolean fp = Boolean.TRUE.equals(d.get("fixed_point"));
        var parts = new ArrayList<Object>();
        for (var item : (List<Object>) d.get("template")) {
            if (item instanceof String s) parts.add(s);
            else parts.add(((Map<String, Object>) item).get("m"));
        }
        return new Template(parts, fp);
    }

    // ── Pipeline ──────────────────────────────────────────────────────────────

    static class Program {
        List<Element> elements;
        boolean fixedPoint;

        Program(List<Element> elements, boolean fixedPoint) {
            this.elements = elements; this.fixedPoint = fixedPoint;
        }
    }

    @SuppressWarnings("unchecked")
    static Object stepFromJson(Map<String, Object> d) {
        String kind = (String) d.get("kind");
        if ("program".equals(kind))
            return new Program(prepareElements(d.get("elements")),
                               Boolean.TRUE.equals(d.get("fixed_point")));
        if ("template".equals(kind))
            return templateFromJson(d);
        throw new RuntimeException("Unknown step kind: " + kind);
    }

    static boolean stepFixedPoint(Object step) {
        return step instanceof Program p ? p.fixedPoint : ((Template) step).fixedPoint;
    }

    // transform: recursively apply step chain to `text`, returning null on failure.
    // committed=true: a Program step with no matches passes through unchanged.
    // committed=false: a Program step with no matches signals failure (null).
    @SuppressWarnings("unchecked")
    static String transform(List<Object> steps, String text, List<HMatch> ancestors, boolean committed) {
        if (steps.isEmpty()) return text;
        var head = steps.get(0);
        var rest = steps.subList(1, steps.size());

        if (head instanceof Template tmpl) {
            var rendered = renderTemplate(tmpl, text, ancestors);
            String full = (String) rendered[0];
            List<int[]> spans = (List<int[]>) rendered[1];
            if (spans == null) {
                // No moustache exprs: whole output is one anonymous stage.
                var newAnc = new ArrayList<>(ancestors);
                newAnc.add(new HMatch(full, 0, full.length(), List.of()));
                return transform(rest, full, newAnc, true);
            }
            if (rest.isEmpty()) return full;
            var sb = new StringBuilder();
            int last = 0;
            for (var span : spans) {
                String payload = full.substring(span[0], span[1]);
                var newAnc = new ArrayList<>(ancestors);
                newAnc.add(new HMatch(payload, 0, payload.length(), List.of()));
                String sub = transform(rest, payload, newAnc, true);
                if (sub == null) return null;
                sb.append(full, last, span[0]);
                sb.append(sub);
                last = span[1];
            }
            sb.append(full.substring(last));
            return sb.toString();
        }

        // Program step
        var prog = (Program) head;
        var sb = new StringBuilder();
        int last = 0;
        boolean matched = false;
        for (var m : findMatches(prog.elements, text, ancestors)) {
            matched = true;
            var newAnc = new ArrayList<>(ancestors);
            newAnc.add(m);
            String sub = transform(rest, m.text, newAnc, committed);
            if (sub == null) return null;
            sb.append(text, last, m.start);
            sb.append(sub);
            last = m.end;
        }
        if (!matched) return committed ? text : null;
        sb.append(text.substring(last));
        return sb.toString();
    }

    record Delta(int start, int end, String text) {}

    static List<Delta> deltas(List<Object> steps, String target) {
        if (steps.isEmpty()) return List.of();
        var head = steps.get(0);
        if (head instanceof Template) {
            String result = transform(steps, target, List.of(), false);
            return result == null ? List.of() : List.of(new Delta(0, target.length(), result));
        }
        var prog = (Program) head;
        var rest = steps.subList(1, steps.size());
        var out = new ArrayList<Delta>();
        for (var m : findMatches(prog.elements, target, List.of())) {
            var anc = List.of(m);
            String result = transform(rest, m.text, anc, false);
            if (result != null) out.add(new Delta(m.start, m.end, result));
        }
        return out;
    }

    static String splice(List<Object> steps, String target) {
        var sb = new StringBuilder();
        int last = 0;
        for (var d : deltas(steps, target)) {
            sb.append(target, last, d.start());
            sb.append(d.text());
            last = d.end();
        }
        return sb.append(target.substring(last)).toString();
    }

    static String spliceToFixedPoint(List<Object> steps, String target) {
        String text = target;
        int cap = 8 * target.length() + 1024;
        int sizeLimit = 64 * target.length() + 65536;
        for (int i = 0; i < cap; i++) {
            String result = splice(steps, text);
            if (result.equals(text)) return text;
            text = result;
            if (text.length() > sizeLimit) break;
        }
        throw new RuntimeException(
            "A `<=` statement did not settle — the rule is not contracting toward a " +
            "fixed point (it grows or oscillates). Use `=>` for a single pass.");
    }

    @SuppressWarnings("unchecked")
    static String runPipeline(List<Object> pipeline, String target) {
        String result = target;
        for (var stmtJson : pipeline) {
            var stmtArr = (List<Object>) stmtJson;
            var steps = new ArrayList<Object>();
            for (var s : stmtArr) steps.add(stepFromJson((Map<String, Object>) s));
            if (steps.isEmpty()) continue;
            result = stepFixedPoint(steps.get(0))
                ? spliceToFixedPoint(steps, result)
                : splice(steps, result);
        }
        return result;
    }

    // ── Entry point ───────────────────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws IOException {
        String input = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        try {
            var payload = (Map<String, Object>) parseJson(input);
            var pipeline = (List<Object>) payload.get("pipeline");
            String target = (String) payload.get("target");
            String result = runPipeline(pipeline, target);
            System.out.println("{" + jsonStr("result") + ":" + jsonStr(result) + "}");
        } catch (Exception ex) {
            String msg = ex.getMessage() != null ? ex.getMessage() : ex.toString();
            System.err.println(msg);
            System.out.println("{" + jsonStr("error") + ":" + jsonStr(msg) + "}");
            System.exit(1);
        }
    }
}
