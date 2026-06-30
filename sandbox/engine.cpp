// Standalone C++17 engine for the himark opcode IR. Zero external dependencies.
//
// Build (C++17):
//   g++ -std=c++17 -O2 -o himark-engine engine.cpp
//
// stdin:  {"pipeline": [[step, ...], ...], "target": "..."}
// stdout: {"result": "..."} | {"error": "..."}
//
// This is a faithful port of the sibling sandbox engines (engine.py / engine.go);
// it operates on UTF-8 byte offsets like the Go engine and must produce
// byte-identical output to all of them.  See docs/ENGINE.md for the design.

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <iterator>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

// ── Opcode constants ────────────────────────────────────────────────────────

enum {
    LIT = 0, ANCHOR = 1, CHAR = 2, GROUP = 3, BACK_REF = 4, COUNT_REF = 5,
    STAGE_REF = 6, VALUE_RANGE = 7, DYN_RANGE = 8, COMPLEMENT = 10, SEQ_GROUP = 11
};

// ── Minimal JSON ────────────────────────────────────────────────────────────
// Values: null, bool, number (double), string, array, object.

struct JsonValue {
    enum Type { Null, Bool, Num, Str, Arr, Obj } type = Null;
    bool b = false;
    double num = 0.0;
    std::string str;
    std::vector<JsonValue> arr;
    std::map<std::string, JsonValue> obj;

    bool isNull() const { return type == Null; }
    bool asBool() const { return type == Bool && b; }
    double asNum() const { return num; }
    const std::string& asStr() const { return str; }
    // Returns nullptr when the key is absent (object) -- mirrors `d.get(key)`.
    const JsonValue* get(const std::string& k) const {
        if (type != Obj) return nullptr;
        auto it = obj.find(k);
        return it == obj.end() ? nullptr : &it->second;
    }
    bool has(const std::string& k) const { return get(k) != nullptr; }
};

struct JsonParser {
    const std::string& s;
    size_t p = 0;
    explicit JsonParser(const std::string& src) : s(src) {}

    void skipWs() {
        while (p < s.size() && (unsigned char)s[p] <= ' ') p++;
    }

    JsonValue parseValue() {
        skipWs();
        if (p >= s.size()) return JsonValue{};
        char c = s[p];
        if (c == '"') return parseString();
        if (c == '[') return parseArray();
        if (c == '{') return parseObject();
        if (c == 't') { p += 4; JsonValue v; v.type = JsonValue::Bool; v.b = true; return v; }
        if (c == 'f') { p += 5; JsonValue v; v.type = JsonValue::Bool; v.b = false; return v; }
        if (c == 'n') { p += 4; return JsonValue{}; }
        return parseNumber();
    }

    JsonValue parseString() {
        JsonValue v; v.type = JsonValue::Str;
        v.str = parseRawString();
        return v;
    }

    std::string parseRawString() {
        p++; // skip opening quote
        std::string out;
        while (p < s.size()) {
            char c = s[p++];
            if (c == '"') break;
            if (c != '\\') { out.push_back(c); continue; }
            char e = s[p++];
            switch (e) {
                case '"': out.push_back('"'); break;
                case '\\': out.push_back('\\'); break;
                case '/': out.push_back('/'); break;
                case 'b': out.push_back('\b'); break;
                case 'f': out.push_back('\f'); break;
                case 'n': out.push_back('\n'); break;
                case 'r': out.push_back('\r'); break;
                case 't': out.push_back('\t'); break;
                case 'u': {
                    unsigned cp = (unsigned)std::stoul(s.substr(p, 4), nullptr, 16);
                    p += 4;
                    encodeUtf8(cp, out);
                    break;
                }
                default: out.push_back(e);
            }
        }
        return out;
    }

    static void encodeUtf8(unsigned cp, std::string& out) {
        if (cp < 0x80) {
            out.push_back((char)cp);
        } else if (cp < 0x800) {
            out.push_back((char)(0xC0 | (cp >> 6)));
            out.push_back((char)(0x80 | (cp & 0x3F)));
        } else {
            out.push_back((char)(0xE0 | (cp >> 12)));
            out.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back((char)(0x80 | (cp & 0x3F)));
        }
    }

    JsonValue parseArray() {
        JsonValue v; v.type = JsonValue::Arr;
        p++; // skip [
        skipWs();
        if (p < s.size() && s[p] == ']') { p++; return v; }
        while (true) {
            v.arr.push_back(parseValue());
            skipWs();
            char c = p < s.size() ? s[p++] : ']';
            if (c == ']') break;
        }
        return v;
    }

    JsonValue parseObject() {
        JsonValue v; v.type = JsonValue::Obj;
        p++; // skip {
        skipWs();
        if (p < s.size() && s[p] == '}') { p++; return v; }
        while (true) {
            skipWs();
            std::string key = parseRawString();
            skipWs();
            p++; // skip :
            v.obj.emplace(std::move(key), parseValue());
            skipWs();
            char c = p < s.size() ? s[p++] : '}';
            if (c == '}') break;
        }
        return v;
    }

    JsonValue parseNumber() {
        size_t start = p;
        if (p < s.size() && s[p] == '-') p++;
        while (p < s.size() && (std::isdigit((unsigned char)s[p]))) p++;
        if (p < s.size() && s[p] == '.') {
            p++;
            while (p < s.size() && std::isdigit((unsigned char)s[p])) p++;
        }
        if (p < s.size() && (s[p] == 'e' || s[p] == 'E')) {
            p++;
            if (p < s.size() && (s[p] == '+' || s[p] == '-')) p++;
            while (p < s.size() && std::isdigit((unsigned char)s[p])) p++;
        }
        JsonValue v; v.type = JsonValue::Num;
        v.num = std::stod(s.substr(start, p - start));
        return v;
    }
};

// Emit a JSON string literal that Python's json.loads round-trips faithfully.
static std::string jsonEscape(const std::string& s) {
    std::string out = "\"";
    for (unsigned char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out.push_back((char)c);
                }
        }
    }
    out.push_back('"');
    return out;
}

// ── UTF-8 + string helpers ──────────────────────────────────────────────────

// Decode one rune; returns {codepoint, byte_length}. Invalid -> {0xFFFD, 1}.
static std::pair<uint32_t, int> decodeRune(const std::string& s, size_t pos) {
    unsigned char c = (unsigned char)s[pos];
    if (c < 0x80) return {c, 1};
    if ((c >> 5) == 0x6 && pos + 1 < s.size())
        return {(uint32_t)(((c & 0x1F) << 6) | (s[pos + 1] & 0x3F)), 2};
    if ((c >> 4) == 0xE && pos + 2 < s.size())
        return {(uint32_t)(((c & 0x0F) << 12) | ((s[pos + 1] & 0x3F) << 6) | (s[pos + 2] & 0x3F)), 3};
    if ((c >> 3) == 0x1E && pos + 3 < s.size())
        return {(uint32_t)(((c & 0x07) << 18) | ((s[pos + 1] & 0x3F) << 12) |
                           ((s[pos + 2] & 0x3F) << 6) | (s[pos + 3] & 0x3F)), 4};
    return {0xFFFD, 1};
}

static bool startsWith(const std::string& s, size_t pos, const std::string& needle) {
    if (needle.size() > s.size() - std::min(pos, s.size())) return false;
    if (pos > s.size()) return false;
    return std::memcmp(s.data() + pos, needle.data(), needle.size()) == 0;
}

// ── Reps ────────────────────────────────────────────────────────────────────

struct Reps {
    int min = 1;
    int max = 1;            // -1 = unbounded
    bool hasAllowed = false;
    std::set<int> allowed;
    int countRef = -1;      // -1 = not a count-ref

    bool accepts(int k) const {
        if (hasAllowed) return allowed.count(k) > 0;
        return k >= min && (max == -1 || k <= max);
    }
};

static int asInt(const JsonValue& v) { return (int)v.asNum(); }

static Reps parseReps(const JsonValue& v) {
    Reps r;
    if (v.isNull() || v.type != JsonValue::Arr || v.arr.empty()) return r;
    const auto& arr = v.arr;
    if (arr[0].type == JsonValue::Str && arr[0].asStr() == "#") {
        r.min = 0; r.max = -1; r.countRef = asInt(arr[1]);
        return r;
    }
    if (arr[0].type == JsonValue::Str && arr[0].asStr() == "=") {
        int lo = INT32_MAX, hi = INT32_MIN;
        for (const auto& x : arr[1].arr) {
            int k = asInt(x);
            r.allowed.insert(k);
            lo = std::min(lo, k);
            hi = std::max(hi, k);
        }
        r.hasAllowed = true; r.min = lo; r.max = hi;
        return r;
    }
    r.min = asInt(arr[0]);
    int hiRaw = asInt(arr[1]);
    r.max = (hiRaw == -1) ? -1 : hiRaw;
    return r;
}

// ── Captures / HMatch ───────────────────────────────────────────────────────

struct Capture {
    std::string text;
    int spanStart = 0;
    int spanEnd = 0;
    std::vector<std::string> reps;     // per-rep text (left empty when count >= 0)
    std::vector<Capture> subs;
    int count = -1;                    // -1 = use reps.size(); >= 0 = deferred count

    int repCount() const { return count >= 0 ? count : (int)reps.size(); }
};

struct HMatch {
    std::string text;
    int start = 0;
    int end = 0;
    std::vector<Capture> captures;

    const Capture* captureAt(const std::vector<int>& path) const {
        const std::vector<Capture>* caps = &captures;
        const Capture* cap = nullptr;
        for (int idx : path) {
            if (idx < 0 || idx >= (int)caps->size()) return nullptr;
            cap = &(*caps)[idx];
            caps = &cap->subs;
        }
        return cap;
    }
};

// ── Exclusions ──────────────────────────────────────────────────────────────

struct Exclusions {
    std::set<uint32_t> singles;
    std::vector<std::pair<uint32_t, uint32_t>> ranges;
    std::vector<std::string> literals;

    // singles + ranges, against the rune at `pos`.
    bool excludesChar(const std::string& text, size_t pos) const {
        auto [r, sz] = decodeRune(text, pos);
        (void)sz;
        if (singles.count(r)) return true;
        for (auto& rg : ranges)
            if (r >= rg.first && r <= rg.second) return true;
        return false;
    }
    bool excludesLiteral(const std::string& candidate) const {
        for (auto& lit : literals)
            if (candidate == lit) return true;
        return false;
    }
};

static std::shared_ptr<Exclusions> parseExcl(const JsonValue& v) {
    if (v.type != JsonValue::Arr || v.arr.size() != 3) return nullptr;
    const auto& singles = v.arr[0].arr;
    const auto& ranges = v.arr[1].arr;
    const auto& lits = v.arr[2].arr;
    if (singles.empty() && ranges.empty() && lits.empty()) return nullptr;
    auto ex = std::make_shared<Exclusions>();
    for (const auto& x : singles) {
        const std::string& sv = x.asStr();
        if (!sv.empty()) ex->singles.insert(decodeRune(sv, 0).first);
    }
    for (const auto& x : ranges) {
        const auto& pair = x.arr;
        ex->ranges.emplace_back(decodeRune(pair[0].asStr(), 0).first,
                                decodeRune(pair[1].asStr(), 0).first);
    }
    for (const auto& x : lits) ex->literals.push_back(x.asStr());
    return ex;
}

// ── Alphabet ────────────────────────────────────────────────────────────────

struct Alphabet {
    virtual ~Alphabet() = default;
    virtual bool containsRune(uint32_t r) const = 0;
    virtual std::optional<double> value(const std::string& s) const = 0;
    virtual int base() const = 0;
};

struct RangeAlphabet : Alphabet {
    int lo, hi;
    RangeAlphabet(int lo_, int hi_) : lo(lo_), hi(hi_) {}
    bool containsRune(uint32_t r) const override { return (int)r >= lo && (int)r <= hi; }
    int base() const override { return hi - lo + 1; }
    std::optional<double> value(const std::string& s) const override {
        double v = 0.0, b = (double)base();
        size_t i = 0;
        while (i < s.size()) {
            auto [r, sz] = decodeRune(s, i);
            if ((int)r < lo || (int)r > hi) return std::nullopt;
            v = v * b + (double)((int)r - lo);
            i += sz;
        }
        return v;
    }
};

struct GroupAlphabet : Alphabet {
    std::map<std::string, int> index;
    int baseN;
    GroupAlphabet(const JsonValue& groups) {
        int i = 0;
        for (const auto& g : groups.arr) {
            for (const auto& m : g.arr) index[m.asStr()] = i;
            i++;
        }
        baseN = i;
    }
    bool containsRune(uint32_t r) const override {
        std::string key;
        JsonParser::encodeUtf8(r, key);
        return index.count(key) > 0;
    }
    int base() const override { return baseN; }
    std::optional<double> value(const std::string& s) const override {
        double v = 0.0, b = (double)baseN;
        for (size_t i = 0; i < s.size();) {
            std::string best;
            int bestIdx = -1;
            for (const auto& kv : index) {
                if (startsWith(s, i, kv.first) && kv.first.size() > best.size()) {
                    best = kv.first;
                    bestIdx = kv.second;
                }
            }
            if (bestIdx < 0) return std::nullopt;
            v = v * b + (double)bestIdx;
            i += best.size();
        }
        return v;
    }
};

static std::shared_ptr<Alphabet> parseAlphabet(const JsonValue& v) {
    const auto& arr = v.arr;
    if (arr[0].asStr() == "range")
        return std::make_shared<RangeAlphabet>(asInt(arr[1]), asInt(arr[2]));
    return std::make_shared<GroupAlphabet>(arr[1]);
}

// ── Matchers ────────────────────────────────────────────────────────────────

struct Matcher {
    virtual ~Matcher() = default;
    virtual std::optional<int> matchOne(const std::string& text, int pos) const = 0;
    virtual bool accepts(const std::string& s) const = 0;
    virtual std::optional<int> equalUnit(const std::string& text, int pos,
                                         const std::string& first) const {
        if (startsWith(text, pos, first)) return pos + (int)first.size();
        return std::nullopt;
    }
};

struct CharMatcher : Matcher {
    int lo, hi;
    const Exclusions* excl;
    CharMatcher(int lo_, int hi_, const Exclusions* e) : lo(lo_), hi(hi_), excl(e) {}
    std::optional<int> matchOne(const std::string& text, int pos) const override {
        if (pos >= (int)text.size()) return std::nullopt;
        auto [r, sz] = decodeRune(text, pos);
        if ((int)r < lo || (int)r > hi) return std::nullopt;
        if (excl) {
            if (excl->excludesChar(text, pos)) return std::nullopt;
            for (const auto& lit : excl->literals)
                if (startsWith(text, pos, lit)) return std::nullopt;
        }
        return pos + sz;
    }
    bool accepts(const std::string& s) const override {
        auto n = matchOne(s, 0);
        return n && *n == (int)s.size();
    }
};

struct GroupMatcher : Matcher {
    std::vector<std::pair<std::string, int>> entries;  // (member, groupIdx), longest-first
    std::set<std::string> acceptSet;
    GroupMatcher(const JsonValue& groups) {
        int i = 0;
        for (const auto& g : groups.arr) {
            for (const auto& m : g.arr) {
                const std::string& s = m.asStr();
                if (!s.empty()) {
                    entries.emplace_back(s, i);
                    acceptSet.insert(s);
                }
            }
            i++;
        }
        std::stable_sort(entries.begin(), entries.end(),
                         [](const auto& a, const auto& b) {
                             return a.first.size() > b.first.size();
                         });
    }
    std::optional<int> matchOne(const std::string& text, int pos) const override {
        for (const auto& e : entries)
            if (startsWith(text, pos, e.first)) return pos + (int)e.first.size();
        return std::nullopt;
    }
    bool accepts(const std::string& s) const override { return acceptSet.count(s) > 0; }
    std::optional<int> equalUnit(const std::string& text, int pos,
                                 const std::string& first) const override {
        // Re-match the group-index sequence of `first` at `pos`.
        std::vector<int> seq;
        size_t i = 0;
        while (i < first.size()) {
            bool found = false;
            for (const auto& e : entries) {
                if (startsWith(first, i, e.first)) {
                    seq.push_back(e.second);
                    i += e.first.size();
                    found = true;
                    break;
                }
            }
            if (!found) return std::nullopt;
        }
        int cur = pos;
        for (int gidx : seq) {
            bool matched = false;
            for (const auto& e : entries) {
                if (e.second == gidx && startsWith(text, cur, e.first)) {
                    cur += (int)e.first.size();
                    matched = true;
                    break;
                }
            }
            if (!matched) return std::nullopt;
        }
        return cur;
    }
};

struct ComplementMatcher : Matcher {
    const std::vector<std::vector<std::string>>* innerGroups;
    ComplementMatcher(const std::vector<std::vector<std::string>>* g) : innerGroups(g) {}
    std::optional<int> matchOne(const std::string& text, int pos) const override {
        if (pos >= (int)text.size()) return std::nullopt;
        auto [r, sz] = decodeRune(text, pos);
        (void)r;
        for (const auto& grp : *innerGroups)
            for (const auto& mem : grp)
                if (!mem.empty() && startsWith(text, pos, mem)) return std::nullopt;
        return pos + sz;
    }
    bool accepts(const std::string& s) const override {
        auto n = matchOne(s, 0);
        return n && *n == (int)s.size();
    }
    std::optional<int> equalUnit(const std::string& text, int pos,
                                 const std::string&) const override {
        return matchOne(text, pos);
    }
};

struct ValueMatcher : Matcher {
    const Alphabet* alph;
    std::optional<double> loVal, hiVal;
    int wmin;
    std::optional<int> wmax;
    const Exclusions* excl;
    ValueMatcher(const Alphabet* a, std::optional<double> lo, std::optional<double> hi,
                 int wmn, std::optional<int> wmx, const Exclusions* e)
        : alph(a), loVal(lo), hiVal(hi), wmin(wmn), wmax(wmx), excl(e) {}
    std::optional<int> matchOne(const std::string& text, int pos) const override {
        int end = pos;
        while (end < (int)text.size()) {
            auto [r, sz] = decodeRune(text, end);
            if (!alph->containsRune(r)) break;
            end += sz;
        }
        int avail = end - pos;
        int top = avail;
        if (wmax && *wmax < top) top = *wmax;
        for (int w = top; w >= wmin; w--) {
            std::string candidate = text.substr(pos, w);
            if (excl) {
                if (excl->excludesLiteral(candidate)) continue;
                if (w == 1 && excl->excludesChar(text, pos)) continue;
            }
            auto val = alph->value(candidate);
            if (!val) continue;
            if (loVal && *val < *loVal) continue;
            if (hiVal && *val > *hiVal) continue;
            return pos + w;
        }
        return std::nullopt;
    }
    bool accepts(const std::string& s) const override {
        auto n = matchOne(s, 0);
        return n && *n == (int)s.size();
    }
};

// ── Referent descriptor (DYN_RANGE endpoints) ───────────────────────────────

struct RefDesc {
    std::string kind;  // "back", "count", "stage"
    int idx;
    std::vector<int> path;
};

static std::shared_ptr<RefDesc> parseRefDesc(const JsonValue& v) {
    if (v.isNull()) return nullptr;
    auto rd = std::make_shared<RefDesc>();
    const auto& arr = v.arr;
    rd->kind = arr[0].asStr();
    rd->idx = asInt(arr[1]);
    if (arr.size() > 2 && !arr[2].isNull())
        for (const auto& x : arr[2].arr) rd->path.push_back(asInt(x));
    return rd;
}

// ── Element (prepared VM instruction) ───────────────────────────────────────

struct Element {
    int op = 0;
    std::string litStr;
    int anchorKind = 0;
    int charLo = 0, charHi = 0;
    std::shared_ptr<GroupMatcher> groupM;
    std::vector<std::vector<std::string>> complementGroups;
    int refIdx = 0;
    int stageIdx = 0;
    std::vector<int> stagePath;
    std::shared_ptr<Alphabet> alph;
    std::optional<double> loVal, hiVal;
    int wmin = 1;
    std::optional<int> wmax;
    std::shared_ptr<std::string> loStatic, hiStatic;
    std::shared_ptr<RefDesc> loRef, hiRef;
    std::vector<Element> children;
    std::shared_ptr<Exclusions> excl;
    Reps reps;
};

static std::optional<double> optDouble(const JsonValue& v) {
    if (v.isNull()) return std::nullopt;
    return v.asNum();
}
static std::optional<int> optInt(const JsonValue& v) {
    if (v.isNull()) return std::nullopt;
    return asInt(v);
}
static std::shared_ptr<std::string> optStr(const JsonValue& v) {
    if (v.isNull()) return nullptr;
    return std::make_shared<std::string>(v.asStr());
}

static std::vector<Element> prepareElements(const JsonValue& raw) {
    std::vector<Element> out;
    out.reserve(raw.arr.size());
    for (const auto& item : raw.arr) {
        const auto& arr = item.arr;
        Element el;
        el.op = asInt(arr[0]);
        switch (el.op) {
            case LIT:
                el.litStr = arr[1].asStr();
                break;
            case ANCHOR:
                el.anchorKind = asInt(arr[1]);
                break;
            case CHAR:  // [2, lo, hi, excl, reps]
                el.charLo = asInt(arr[1]);
                el.charHi = asInt(arr[2]);
                el.excl = parseExcl(arr[3]);
                el.reps = parseReps(arr[4]);
                break;
            case GROUP:  // [3, groups, het, reps]
                el.groupM = std::make_shared<GroupMatcher>(arr[1]);
                el.reps = parseReps(arr[3]);
                break;
            case BACK_REF:  // [4, group, reps]
            case COUNT_REF:  // [5, group, reps]
                el.refIdx = asInt(arr[1]);
                el.reps = parseReps(arr[2]);
                break;
            case STAGE_REF: {  // [6, stage, path, reps]
                el.stageIdx = asInt(arr[1]);
                for (const auto& x : arr[2].arr) el.stagePath.push_back(asInt(x));
                el.reps = parseReps(arr[3]);
                break;
            }
            case VALUE_RANGE:  // [7, alph, lo_val, hi_val, wmin, wmax, excl, reps]
                el.alph = parseAlphabet(arr[1]);
                el.loVal = optDouble(arr[2]);
                el.hiVal = optDouble(arr[3]);
                el.wmin = asInt(arr[4]);
                el.wmax = optInt(arr[5]);
                el.excl = parseExcl(arr[6]);
                el.reps = parseReps(arr[7]);
                break;
            case DYN_RANGE:  // [8, alph, lo_static, hi_static, lo_ref, hi_ref, excl, reps]
                el.alph = parseAlphabet(arr[1]);
                el.loStatic = optStr(arr[2]);
                el.hiStatic = optStr(arr[3]);
                el.loRef = parseRefDesc(arr[4]);
                el.hiRef = parseRefDesc(arr[5]);
                el.excl = parseExcl(arr[6]);
                el.reps = parseReps(arr[7]);
                break;
            case COMPLEMENT: {  // [10, inner_groups, reps]
                for (const auto& g : arr[1].arr) {
                    std::vector<std::string> row;
                    for (const auto& m : g.arr) row.push_back(m.asStr());
                    el.complementGroups.push_back(std::move(row));
                }
                el.reps = parseReps(arr[2]);
                break;
            }
            case SEQ_GROUP:  // [11, children, reps]
                el.children = prepareElements(arr[1]);
                el.reps = parseReps(arr[2]);
                break;
            default:
                throw std::runtime_error("unknown opcode: " + std::to_string(el.op));
        }
        out.push_back(std::move(el));
    }
    return out;
}

// ── VM state ────────────────────────────────────────────────────────────────

struct State {
    std::vector<Capture> captures;
    const std::vector<const HMatch*>* stages;
    int rootLen;  // INT32_MAX when unrestricted; set by outermost SEQ_GROUP

    explicit State(const std::vector<const HMatch*>* s) : stages(s), rootLen(INT32_MAX) {}

    int captureLimit() const {
        if (rootLen == INT32_MAX) return (int)captures.size();
        return std::min(rootLen, (int)captures.size());
    }
};

// ── Forward declarations ────────────────────────────────────────────────────

static std::optional<int> runProgram(const std::vector<Element>& elements, int idx,
                                     const std::string& text, int pos, State& st);

// ── Reference resolution ────────────────────────────────────────────────────

static std::optional<std::string> resolveBack(int idx, State& st, const std::string& text) {
    int lim = st.captureLimit();
    if (idx >= lim) return std::nullopt;
    const Capture& c = st.captures[idx];
    return text.substr(c.spanStart, c.spanEnd - c.spanStart);
}

static std::optional<std::string> resolveCount(int idx, State& st) {
    int lim = st.captureLimit();
    if (idx >= lim) return std::nullopt;
    return std::to_string(st.captures[idx].repCount());
}

static std::optional<std::string> resolveStage(int stageIdx, const std::vector<int>& path,
                                               State& st) {
    if (stageIdx < 0 || stageIdx >= (int)st.stages->size()) return std::nullopt;
    const HMatch* m = (*st.stages)[stageIdx];
    if (path.empty()) return m->text;
    const Capture* cap = m->captureAt(path);
    if (!cap) return std::nullopt;
    return cap->text;
}

static std::optional<std::string> resolveRefDescVal(const RefDesc& rd, State& st,
                                                    const std::string& text) {
    if (rd.kind == "back") return resolveBack(rd.idx, st, text);
    if (rd.kind == "count") return resolveCount(rd.idx, st);
    if (rd.kind == "stage") return resolveStage(rd.idx, rd.path, st);
    return std::nullopt;
}

static std::optional<Reps> resolveReps(const Reps& r, State& st) {
    if (r.countRef < 0) return r;
    int lim = st.captureLimit();
    if (r.countRef >= lim) return std::nullopt;
    int k = st.captures[r.countRef].repCount();
    Reps nr; nr.min = k; nr.max = k;
    return nr;
}

// ── push / rollback helper ──────────────────────────────────────────────────

template <class Cont>
static std::optional<int> pushCap(State& st, Capture&& cap, int end, Cont cont) {
    size_t mark = st.captures.size();
    st.captures.push_back(std::move(cap));
    auto result = cont(end);
    if (!result) st.captures.resize(mark);
    return result;
}

// ── counts: candidate repetition counts, greedy-first then zero ─────────────

static std::vector<int> counts(const Reps& r, int built) {
    std::vector<int> ks;
    for (int k = built; k >= 1; k--)
        if (r.accepts(k)) ks.push_back(k);
    if (r.accepts(0)) ks.push_back(0);
    return ks;
}

// ── Anchors ─────────────────────────────────────────────────────────────────

static bool checkAnchor(int kind, const std::string& text, int pos) {
    switch (kind) {
        case 0: return pos == 0 || text[pos - 1] == '\n';
        case 1: return pos == (int)text.size() || text[pos] == '\n';
        case 2: return pos == 0;
        case 3: return pos == (int)text.size();
    }
    return false;
}

// ── Matcher driver ──────────────────────────────────────────────────────────

static std::optional<int> runMatcher(const Matcher& m, const Reps& reps,
                                     const std::vector<Element>& elements, int nextIdx,
                                     State& st, const std::string& text, int pos) {
    auto cont = [&](int end) { return runProgram(elements, nextIdx, text, end, st); };

    auto tryZero = [&]() -> std::optional<int> {
        if (!reps.accepts(0)) return std::nullopt;
        Capture cap; cap.spanStart = pos; cap.spanEnd = pos; cap.count = 0;
        return pushCap(st, std::move(cap), pos, cont);
    };

    auto firstEnd = m.matchOne(text, pos);
    if (!firstEnd || *firstEnd == pos) return tryZero();

    for (int unitLen = *firstEnd - pos; unitLen >= 1; unitLen--) {
        std::string first = text.substr(pos, unitLen);
        if (!m.accepts(first)) continue;

        // Only the rep *count* is ever read, so we keep just the boundaries and
        // defer materialisation: each candidate count k pushes an empty reps list
        // with count = k (O(1)).  See docs/ENGINE.md section 5.
        std::vector<int> ends{pos + unitLen};
        int current = pos + unitLen;
        while (reps.max == -1 || (int)ends.size() < reps.max) {
            auto nxt = m.equalUnit(text, current, first);
            if (!nxt) break;
            ends.push_back(*nxt);
            current = *nxt;
        }

        for (int k : counts(reps, (int)ends.size())) {
            int end = (k == 0) ? pos : ends[k - 1];
            Capture cap; cap.spanStart = pos; cap.spanEnd = end; cap.count = k;
            auto r = pushCap(st, std::move(cap), end, cont);
            if (r) return r;
        }
    }
    return tryZero();
}

// ── Referent matching (BACK_REF / COUNT_REF / STAGE_REF) ────────────────────

static std::optional<int> matchReferent(const std::optional<std::string>& referent,
                                        const Reps& reps,
                                        const std::vector<Element>& elements, int nextIdx,
                                        const std::string& text, int pos, State& st) {
    if (!referent) return std::nullopt;
    const std::string& ref = *referent;
    auto cont = [&](int end) { return runProgram(elements, nextIdx, text, end, st); };

    if (ref.empty()) {
        Capture cap; cap.spanStart = pos; cap.spanEnd = pos;
        cap.reps.assign(reps.min, std::string());
        return pushCap(st, std::move(cap), pos, cont);
    }

    std::vector<int> ends{pos};
    int cur = pos;
    while ((reps.max == -1 || (int)ends.size() - 1 < reps.max) && startsWith(text, cur, ref)) {
        cur += (int)ref.size();
        ends.push_back(cur);
    }
    for (int k : counts(reps, (int)ends.size() - 1)) {
        int end = ends[k];
        Capture cap;
        cap.text = text.substr(pos, end - pos);
        cap.spanStart = pos; cap.spanEnd = end;
        cap.reps.assign(k, ref);
        auto r = pushCap(st, std::move(cap), end, cont);
        if (r) return r;
    }
    return std::nullopt;
}

// ── SEQ_GROUP ───────────────────────────────────────────────────────────────

static std::optional<int> matchSeqGroup(const std::vector<Element>& children, const Reps& reps,
                                        const std::vector<Element>& elements, int nextIdx,
                                        const std::string& text, int pos, State& st) {
    int prevRootLen = st.rootLen;
    if (st.rootLen == INT32_MAX) st.rootLen = (int)st.captures.size();

    struct Run { int end; std::vector<Capture> caps; };
    std::vector<Run> runs;
    int cur = pos;

    while (reps.max == -1 || (int)runs.size() < reps.max) {
        size_t snapLen = st.captures.size();
        auto end = runProgram(children, 0, text, cur, st);
        if (end && *end > cur) {
            std::vector<Capture> subCaps(
                std::make_move_iterator(st.captures.begin() + snapLen),
                std::make_move_iterator(st.captures.end()));
            st.captures.resize(snapLen);
            runs.push_back({*end, std::move(subCaps)});
            cur = *end;
        } else {
            st.captures.resize(snapLen);
            break;
        }
    }

    st.rootLen = prevRootLen;
    auto cont = [&](int end) { return runProgram(elements, nextIdx, text, end, st); };

    for (int k : counts(reps, (int)runs.size())) {
        int end = (k == 0) ? pos : runs[k - 1].end;
        std::vector<std::string> repTexts(k);
        std::vector<Capture> subs;
        for (int i = 0; i < k; i++) {
            int start = (i == 0) ? pos : runs[i - 1].end;
            repTexts[i] = text.substr(start, runs[i].end - start);
            for (const auto& c : runs[i].caps) subs.push_back(c);
        }
        Capture cap;
        cap.text = text.substr(pos, end - pos);
        cap.spanStart = pos; cap.spanEnd = end;
        cap.reps = std::move(repTexts);
        cap.subs = std::move(subs);
        auto r = pushCap(st, std::move(cap), end, cont);
        if (r) return r;
    }
    return std::nullopt;
}

// ── DYN_RANGE matcher builder ───────────────────────────────────────────────

static std::shared_ptr<ValueMatcher> buildDynMatcher(const std::shared_ptr<Alphabet>& alph,
                                                     const std::string* lower,
                                                     const std::string* upper,
                                                     const Exclusions* excl) {
    std::optional<double> loVal, hiVal;
    int wmin = 1;
    std::optional<int> wmax;
    int wf = -1, wc = -1;
    if (lower) {
        auto v = alph->value(*lower);
        if (!v) return nullptr;
        loVal = v;
        wf = (int)lower->size();
    }
    if (upper) {
        auto v = alph->value(*upper);
        if (!v) return nullptr;
        hiVal = v;
        wc = (int)upper->size();
    }
    if (wf >= 0 && wc >= 0) {
        wmin = std::min(wf, wc);
        wmax = std::max(wf, wc);
    } else if (wf >= 0) {
        wmin = wf;
    } else if (wc >= 0) {
        wmin = 1;
        wmax = wc;
    } else {
        wmin = 1;
    }
    return std::make_shared<ValueMatcher>(alph.get(), loVal, hiVal, wmin, wmax, excl);
}

// ── Core VM dispatch ────────────────────────────────────────────────────────

static std::optional<int> runProgram(const std::vector<Element>& elements, int idx,
                                     const std::string& text, int pos, State& st) {
    if (idx >= (int)elements.size()) return pos;
    const Element& e = elements[idx];
    int next = idx + 1;

    switch (e.op) {
        case LIT:
            if (startsWith(text, pos, e.litStr))
                return runProgram(elements, next, text, pos + (int)e.litStr.size(), st);
            return std::nullopt;

        case ANCHOR:
            if (checkAnchor(e.anchorKind, text, pos))
                return runProgram(elements, next, text, pos, st);
            return std::nullopt;

        case CHAR: {
            auto r = resolveReps(e.reps, st);
            if (!r) return std::nullopt;
            CharMatcher m(e.charLo, e.charHi, e.excl.get());
            return runMatcher(m, *r, elements, next, st, text, pos);
        }

        case GROUP: {
            auto r = resolveReps(e.reps, st);
            if (!r) return std::nullopt;
            return runMatcher(*e.groupM, *r, elements, next, st, text, pos);
        }

        case COMPLEMENT: {
            auto r = resolveReps(e.reps, st);
            if (!r) return std::nullopt;
            ComplementMatcher m(&e.complementGroups);
            return runMatcher(m, *r, elements, next, st, text, pos);
        }

        case BACK_REF: {
            auto r = resolveReps(e.reps, st);
            if (!r) return std::nullopt;
            return matchReferent(resolveBack(e.refIdx, st, text), *r, elements, next, text, pos, st);
        }

        case COUNT_REF: {
            auto r = resolveReps(e.reps, st);
            if (!r) return std::nullopt;
            return matchReferent(resolveCount(e.refIdx, st), *r, elements, next, text, pos, st);
        }

        case STAGE_REF: {
            auto r = resolveReps(e.reps, st);
            if (!r) return std::nullopt;
            return matchReferent(resolveStage(e.stageIdx, e.stagePath, st), *r, elements, next, text, pos, st);
        }

        case VALUE_RANGE: {
            auto r = resolveReps(e.reps, st);
            if (!r) return std::nullopt;
            ValueMatcher m(e.alph.get(), e.loVal, e.hiVal, e.wmin, e.wmax, e.excl.get());
            return runMatcher(m, *r, elements, next, st, text, pos);
        }

        case DYN_RANGE: {
            auto r = resolveReps(e.reps, st);
            if (!r) return std::nullopt;
            const std::string* lower = e.loStatic.get();
            const std::string* upper = e.hiStatic.get();
            std::string lowerBuf, upperBuf;
            if (e.loRef) {
                auto s = resolveRefDescVal(*e.loRef, st, text);
                if (!s) return std::nullopt;
                lowerBuf = *s; lower = &lowerBuf;
            }
            if (e.hiRef) {
                auto s = resolveRefDescVal(*e.hiRef, st, text);
                if (!s) return std::nullopt;
                upperBuf = *s; upper = &upperBuf;
            }
            auto m = buildDynMatcher(e.alph, lower, upper, e.excl.get());
            if (!m) return std::nullopt;
            return runMatcher(*m, *r, elements, next, st, text, pos);
        }

        case SEQ_GROUP: {
            auto r = resolveReps(e.reps, st);
            if (!r) return std::nullopt;
            return matchSeqGroup(e.children, *r, elements, next, text, pos, st);
        }
    }
    return std::nullopt;
}

// ── findMatches / finalize ──────────────────────────────────────────────────

static void settleCapture(Capture& c, const std::string& text, int start) {
    if (c.count >= 0 && (int)c.reps.size() > c.count) c.reps.resize(c.count);
    c.text = text.substr(c.spanStart, c.spanEnd - c.spanStart);
    c.spanStart -= start;
    c.spanEnd -= start;
    for (auto& s : c.subs) settleCapture(s, text, start);
}

static HMatch finalize(const std::string& text, int start, int end, State& st) {
    for (auto& c : st.captures) settleCapture(c, text, start);
    HMatch m;
    m.text = text.substr(start, end - start);
    m.start = start;
    m.end = end;
    m.captures = std::move(st.captures);
    return m;
}

static std::vector<HMatch> findMatches(const std::vector<Element>& elements,
                                      const std::string& text,
                                      const std::vector<const HMatch*>& stages) {
    std::vector<HMatch> matches;
    int n = (int)text.size();
    int pos = 0;
    while (pos < n) {
        State st(&stages);
        auto end = runProgram(elements, 0, text, pos, st);
        if (end && *end > pos) {
            matches.push_back(finalize(text, pos, *end, st));
            pos = *end;
        } else {
            pos++;
        }
    }
    return matches;
}

// ── Template rendering ──────────────────────────────────────────────────────

static std::string indentStr(const std::string& s) {
    if (s.empty()) return "";
    std::string out = "\t";
    for (char c : s) {
        out.push_back(c);
        if (c == '\n') out.push_back('\t');
    }
    return out;
}

static std::string trimStr(const std::string& s) {
    size_t a = 0, b = s.size();
    auto isws = [](unsigned char c) { return c == ' ' || c == '\t' || c == '\n' ||
                                             c == '\r' || c == '\f' || c == '\v'; };
    while (a < b && isws(s[a])) a++;
    while (b > a && isws(s[b - 1])) b--;
    return s.substr(a, b - a);
}

static std::string evalExpr(const JsonValue& d, const std::string& current,
                            const std::vector<const HMatch*>& stages) {
    if (d.has("lit")) return d.get("lit")->asStr();
    if (d.has("cur")) return current;
    if (const JsonValue* ref = d.get("ref")) {
        const auto& arr = ref->arr;
        int pipeIdx = arr[0].isNull() ? (int)stages.size() - 1 : asInt(arr[0]);
        bool isCount = arr[1].asBool();
        if (pipeIdx < 0 || pipeIdx >= (int)stages.size())
            throw std::runtime_error("Moustache stage " + std::to_string(pipeIdx) + " out of range");
        const HMatch* sm = stages[pipeIdx];
        if (arr[2].isNull()) return sm->text;
        std::vector<int> path;
        for (const auto& x : arr[2].arr) path.push_back(asInt(x));
        const Capture* cap = sm->captureAt(path);
        if (!cap) throw std::runtime_error("Moustache capture out of range");
        return isCount ? std::to_string(cap->repCount()) : cap->text;
    }
    if (const JsonValue* cat = d.get("cat")) {
        std::string out;
        for (const auto& p : cat->arr) out += evalExpr(p, current, stages);
        return out;
    }
    if (const JsonValue* filt = d.get("filter")) {
        std::string val = evalExpr(*d.get("src"), current, stages);
        const std::string& name = filt->asStr();
        if (name == "trim") return trimStr(val);
        if (name == "indent") return indentStr(val);
        throw std::runtime_error("Unknown template filter: '" + name + "'");
    }
    throw std::runtime_error("Unknown expression node");
}

// Returns the rendered text and, when any moustache appeared, their output spans.
static std::pair<std::string, std::optional<std::vector<std::pair<int, int>>>>
renderTemplate(const std::vector<JsonValue>& parts, const std::string& current,
               const std::vector<const HMatch*>& stages) {
    std::string out;
    std::vector<std::pair<int, int>> spans;
    int pos = 0;
    for (const auto& p : parts) {
        if (p.type == JsonValue::Str) {
            out += p.asStr();
            pos += (int)p.asStr().size();
        } else {
            std::string val = evalExpr(p, current, stages);
            spans.emplace_back(pos, pos + (int)val.size());
            out += val;
            pos += (int)val.size();
        }
    }
    if (spans.empty()) return {out, std::nullopt};
    return {out, spans};
}

// ── Steps ───────────────────────────────────────────────────────────────────

struct Step {
    bool isTemplate;
    bool fixedPoint;
    std::vector<Element> elements;     // program
    std::vector<JsonValue> parts;      // template (literal strings + moustache exprs)
};

static Step jsonToStep(const JsonValue& d) {
    Step step;
    const JsonValue* kindV = d.get("kind");
    std::string kind = kindV ? kindV->asStr() : "";
    const JsonValue* fp = d.get("fixed_point");
    step.fixedPoint = fp && fp->asBool();

    if (kind == "program" || kind == "query") {
        const JsonValue* els = d.get("elements");
        if (els) step.elements = prepareElements(*els);
        step.isTemplate = false;
        return step;
    }
    if (kind == "template") {
        step.isTemplate = true;
        const JsonValue* tmpl = d.get("template");
        if (tmpl) {
            for (const auto& p : tmpl->arr) {
                if (p.type == JsonValue::Str) {
                    step.parts.push_back(p);
                } else if (const JsonValue* m = p.get("m")) {
                    step.parts.push_back(*m);
                }
            }
        }
        return step;
    }
    throw std::runtime_error("Unknown step kind: " + kind);
}

// ── Pipeline execution ──────────────────────────────────────────────────────

struct Delta { int start, end; std::string text; };

// Returns nullopt to signal "no match" (the committed=false failure path).
static std::optional<std::string> transform(const std::vector<Step>& steps, size_t si,
                                            const std::string& text,
                                            std::vector<const HMatch*> ancestors,
                                            bool committed) {
    if (si >= steps.size()) return text;
    const Step& head = steps[si];

    if (head.isTemplate) {
        auto [full, spans] = renderTemplate(head.parts, text, ancestors);
        if (!spans) {
            HMatch stage;
            stage.text = full; stage.start = 0; stage.end = (int)full.size();
            auto anc = ancestors;
            anc.push_back(&stage);
            return transform(steps, si + 1, full, std::move(anc), true);
        }
        if (si + 1 >= steps.size()) return full;
        std::string out;
        int last = 0;
        for (auto& sp : *spans) {
            std::string payload = full.substr(sp.first, sp.second - sp.first);
            HMatch stage;
            stage.text = payload; stage.start = 0; stage.end = (int)payload.size();
            auto anc = ancestors;
            anc.push_back(&stage);
            auto sub = transform(steps, si + 1, payload, std::move(anc), true);
            if (!sub) return std::nullopt;
            out += full.substr(last, sp.first - last);
            out += *sub;
            last = sp.second;
        }
        out += full.substr(last);
        return out;
    }

    std::vector<HMatch> matches = findMatches(head.elements, text, ancestors);
    if (matches.empty()) {
        if (committed) return text;
        return std::nullopt;
    }
    std::string out;
    int last = 0;
    for (auto& m : matches) {
        auto anc = ancestors;
        anc.push_back(&m);
        auto sub = transform(steps, si + 1, m.text, std::move(anc), committed);
        if (!sub) return std::nullopt;
        out += text.substr(last, m.start - last);
        out += *sub;
        last = m.end;
    }
    out += text.substr(last);
    return out;
}

static std::vector<Delta> computeDeltas(const std::vector<Step>& steps, const std::string& target) {
    std::vector<Delta> out;
    if (steps.empty()) return out;
    if (steps[0].isTemplate) {
        auto result = transform(steps, 0, target, {}, false);
        if (result) out.push_back({0, (int)target.size(), *result});
        return out;
    }
    std::vector<HMatch> matches = findMatches(steps[0].elements, target, {});
    for (auto& m : matches) {
        std::vector<const HMatch*> anc{&m};
        auto result = transform(steps, 1, m.text, std::move(anc), false);
        if (result) out.push_back({m.start, m.end, *result});
    }
    return out;
}

static std::string splice(const std::vector<Step>& steps, const std::string& target) {
    std::string out;
    int last = 0;
    for (auto& d : computeDeltas(steps, target)) {
        out += target.substr(last, d.start - last);
        out += d.text;
        last = d.end;
    }
    out += target.substr(last);
    return out;
}

static std::string spliceToFixedPoint(const std::vector<Step>& steps, const std::string& target) {
    std::string text = target;
    long cap = 8L * (long)target.size() + 1024;
    size_t sizeLimit = 64 * target.size() + 65536;
    for (long i = 0; i < cap; i++) {
        std::string result = splice(steps, text);
        if (result == text) return text;
        text = std::move(result);
        if (text.size() > sizeLimit) break;
    }
    throw std::runtime_error(
        "A `<=` statement did not settle — the rule is not contracting toward a "
        "fixed point (it grows or oscillates). Use `=>` for a single pass.");
}

static std::string runPipeline(const JsonValue& pipeline, const std::string& target) {
    std::string result = target;
    for (const auto& stmtJson : pipeline.arr) {
        if (stmtJson.arr.empty()) continue;
        std::vector<Step> steps;
        for (const auto& sj : stmtJson.arr) steps.push_back(jsonToStep(sj));
        if (steps.empty()) continue;
        if (steps[0].fixedPoint) result = spliceToFixedPoint(steps, result);
        else result = splice(steps, result);
    }
    return result;
}

// ── Entry point ─────────────────────────────────────────────────────────────

int main() {
    std::string input((std::istreambuf_iterator<char>(std::cin)),
                      std::istreambuf_iterator<char>());
    try {
        JsonParser parser(input);
        JsonValue payload = parser.parseValue();
        const JsonValue* pipeline = payload.get("pipeline");
        const JsonValue* target = payload.get("target");
        if (!pipeline || !target) {
            std::cout << "{\"error\": \"missing 'pipeline' or 'target'\"}\n";
            return 1;
        }
        std::string result = runPipeline(*pipeline, target->asStr());
        std::cout << "{\"result\": " << jsonEscape(result) << "}\n";
    } catch (const std::exception& exc) {
        std::cout << "{\"error\": " << jsonEscape(exc.what()) << "}\n";
        return 1;
    }
    return 0;
}
