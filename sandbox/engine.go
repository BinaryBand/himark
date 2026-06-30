// Standalone Go engine for the himark opcode IR.
//
// stdin:  {"pipeline": [[step, ...], ...], "target": "..."}
// stdout: {"result": "..."} | {"error": "..."}
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"sort"
	"strings"
	"unicode/utf8"
)

// ---------------------------------------------------------------------------
// Opcode constants
// ---------------------------------------------------------------------------

const (
	opLIT        = 0
	opANCHOR     = 1
	opCHAR       = 2
	opGROUP      = 3
	opBACKREF    = 4
	opCOUNTREF   = 5
	opSTAGEREF   = 6
	opVALUERANGE = 7
	opDYNRANGE   = 8
	opCOMPLEMENT = 10
	opSEQGROUP   = 11
)

// ---------------------------------------------------------------------------
// Reps
// ---------------------------------------------------------------------------

type reps struct {
	min      int
	max      int          // -1 = unbounded
	allowed  map[int]bool // non-nil only for "=" form
	countRef int          // -1 = not a count-ref
}

func (r reps) accepts(k int) bool {
	if r.allowed != nil {
		return r.allowed[k]
	}
	return k >= r.min && (r.max == -1 || k <= r.max)
}

func parseReps(v any) reps {
	if v == nil {
		return reps{min: 1, max: 1, countRef: -1}
	}
	arr, ok := v.([]any)
	if !ok || len(arr) == 0 {
		return reps{min: 1, max: 1, countRef: -1}
	}
	if s, ok := arr[0].(string); ok {
		if s == "#" {
			return reps{countRef: int(arr[1].(float64))}
		}
		if s == "=" {
			vals := arr[1].([]any)
			m := make(map[int]bool, len(vals))
			mn, mx := math.MaxInt, math.MinInt
			for _, x := range vals {
				k := int(x.(float64))
				m[k] = true
				if k < mn {
					mn = k
				}
				if k > mx {
					mx = k
				}
			}
			return reps{min: mn, max: mx, allowed: m, countRef: -1}
		}
	}
	lo := int(arr[0].(float64))
	hi := int(arr[1].(float64))
	return reps{min: lo, max: hi, countRef: -1}
}

func resolveReps(r reps, st *state) *reps {
	if r.countRef < 0 {
		return &r
	}
	lim := st.captureLimit()
	if r.countRef >= lim {
		return nil
	}
	k := st.captures[r.countRef].repCount()
	nr := reps{min: k, max: k, countRef: -1}
	return &nr
}

func counts(r reps, built int) []int {
	var ks []int
	for k := built; k >= 1; k-- {
		if r.accepts(k) {
			ks = append(ks, k)
		}
	}
	if r.accepts(0) {
		ks = append(ks, 0)
	}
	return ks
}

// ---------------------------------------------------------------------------
// Capture / HMatch
// ---------------------------------------------------------------------------

type capture struct {
	text      string
	spanStart int
	spanEnd   int
	repsList  []string
	subs      []*capture
	count     int // -1 = use len(repsList)
}

func (c *capture) repCount() int {
	if c.count >= 0 {
		return c.count
	}
	return len(c.repsList)
}

type hmatch struct {
	text     string
	start    int
	end      int
	captures []*capture
}

func (m *hmatch) captureAt(path []int) *capture {
	caps := m.captures
	var cap *capture
	for _, idx := range path {
		if idx < 0 || idx >= len(caps) {
			return nil
		}
		cap = caps[idx]
		caps = cap.subs
	}
	return cap
}

// ---------------------------------------------------------------------------
// Exclusions
// ---------------------------------------------------------------------------

type exclusions struct {
	singles  map[rune]bool
	ranges   [][2]rune
	literals []string
}

func parseExcl(v any) *exclusions {
	arr, ok := v.([]any)
	if !ok || len(arr) != 3 {
		return nil
	}
	singlesRaw, _ := arr[0].([]any)
	rangesRaw, _ := arr[1].([]any)
	litsRaw, _ := arr[2].([]any)
	if len(singlesRaw)+len(rangesRaw)+len(litsRaw) == 0 {
		return nil
	}
	ex := &exclusions{}
	if len(singlesRaw) > 0 {
		ex.singles = make(map[rune]bool, len(singlesRaw))
		for _, x := range singlesRaw {
			s := x.(string)
			if len(s) > 0 {
				r, _ := utf8.DecodeRuneInString(s)
				ex.singles[r] = true
			}
		}
	}
	for _, x := range rangesRaw {
		pair := x.([]any)
		lo, _ := utf8.DecodeRuneInString(pair[0].(string))
		hi, _ := utf8.DecodeRuneInString(pair[1].(string))
		ex.ranges = append(ex.ranges, [2]rune{lo, hi})
	}
	for _, x := range litsRaw {
		ex.literals = append(ex.literals, x.(string))
	}
	return ex
}

func (ex *exclusions) excludesChar(text string, pos int) bool {
	if ex == nil {
		return false
	}
	r, _ := utf8.DecodeRuneInString(text[pos:])
	if ex.singles[r] {
		return true
	}
	for _, rng := range ex.ranges {
		if r >= rng[0] && r <= rng[1] {
			return true
		}
	}
	return false
}

func (ex *exclusions) excludesLiteral(candidate string) bool {
	if ex == nil {
		return false
	}
	for _, lit := range ex.literals {
		if candidate == lit {
			return true
		}
	}
	return false
}

func (ex *exclusions) excludesAt(text string, pos int) bool {
	if ex.excludesChar(text, pos) {
		return true
	}
	for _, lit := range ex.literals {
		if strings.HasPrefix(text[pos:], lit) {
			return true
		}
	}
	return false
}

// ---------------------------------------------------------------------------
// Alphabet
// ---------------------------------------------------------------------------

type alphabet interface {
	containsRune(r rune) bool
	value(s string) (float64, bool)
	base() int
}

type rangeAlphabet struct {
	lo, hi int
}

func (a *rangeAlphabet) containsRune(r rune) bool {
	return int(r) >= a.lo && int(r) <= a.hi
}

func (a *rangeAlphabet) base() int { return a.hi - a.lo + 1 }

func (a *rangeAlphabet) value(s string) (float64, bool) {
	v := 0.0
	b := float64(a.base())
	for _, r := range s {
		if int(r) < a.lo || int(r) > a.hi {
			return 0, false
		}
		v = v*b + float64(int(r)-a.lo)
	}
	return v, true
}

type groupAlphabet struct {
	index map[string]int
	baseN int
}

func (a *groupAlphabet) containsRune(r rune) bool {
	_, ok := a.index[string(r)]
	return ok
}

func (a *groupAlphabet) base() int { return a.baseN }

func (a *groupAlphabet) value(s string) (float64, bool) {
	v := 0.0
	b := float64(a.baseN)
	// scan multi-char group members greedily
	for i := 0; i < len(s); {
		matched := false
		// try longest possible match first -- scan all keys
		best := ""
		bestIdx := -1
		for mem, idx := range a.index {
			if strings.HasPrefix(s[i:], mem) && len(mem) > len(best) {
				best = mem
				bestIdx = idx
			}
		}
		if bestIdx < 0 {
			return 0, false
		}
		v = v*b + float64(bestIdx)
		i += len(best)
		matched = true
		_ = matched
	}
	return v, true
}

func parseAlphabet(v any) alphabet {
	arr := v.([]any)
	switch arr[0].(string) {
	case "range":
		return &rangeAlphabet{lo: int(arr[1].(float64)), hi: int(arr[2].(float64))}
	default: // "groups"
		groups := arr[1].([]any)
		idx := make(map[string]int)
		for i, g := range groups {
			for _, m := range g.([]any) {
				idx[m.(string)] = i
			}
		}
		return &groupAlphabet{index: idx, baseN: len(groups)}
	}
}

// ---------------------------------------------------------------------------
// Matchers
// ---------------------------------------------------------------------------

type matcher interface {
	matchOne(text string, pos int) (int, bool)
	accepts(s string) bool
	equalUnit(text string, pos int, first string) (int, bool)
}

// charMatcher matches exactly one code point in [lo, hi] with optional exclusions.
type charMatcher struct {
	lo, hi int
	excl   *exclusions
}

func (m *charMatcher) matchOne(text string, pos int) (int, bool) {
	if pos >= len(text) {
		return 0, false
	}
	r, size := utf8.DecodeRuneInString(text[pos:])
	if int(r) < m.lo || int(r) > m.hi {
		return 0, false
	}
	if m.excl != nil && m.excl.excludesChar(text, pos) {
		return 0, false
	}
	return pos + size, true
}

func (m *charMatcher) accepts(s string) bool {
	n, ok := m.matchOne(s, 0)
	return ok && n == len(s)
}

func (m *charMatcher) equalUnit(text string, pos int, first string) (int, bool) {
	if strings.HasPrefix(text[pos:], first) {
		return pos + len(first), true
	}
	return 0, false
}

// groupMatcher matches one position from a symbol set (sorted longest-first).
type groupEntry struct {
	member   string
	groupIdx int
}

type groupMatcher struct {
	entries   []groupEntry
	acceptSet map[string]bool
}

func newGroupMatcher(groups []any) *groupMatcher {
	var entries []groupEntry
	accept := make(map[string]bool)
	for i, g := range groups {
		for _, m := range g.([]any) {
			s := m.(string)
			if s != "" {
				entries = append(entries, groupEntry{s, i})
				accept[s] = true
			}
		}
	}
	sort.Slice(entries, func(i, j int) bool {
		return len(entries[i].member) > len(entries[j].member)
	})
	return &groupMatcher{entries: entries, acceptSet: accept}
}

func (m *groupMatcher) matchOne(text string, pos int) (int, bool) {
	for _, e := range m.entries {
		if strings.HasPrefix(text[pos:], e.member) {
			return pos + len(e.member), true
		}
	}
	return 0, false
}

func (m *groupMatcher) accepts(s string) bool {
	return m.acceptSet[s]
}

// equalUnit re-matches the group-index sequence of first at pos.
func (m *groupMatcher) equalUnit(text string, pos int, first string) (int, bool) {
	// decode first into a sequence of group indices
	var seq []int
	i := 0
	for i < len(first) {
		found := false
		for _, e := range m.entries {
			if strings.HasPrefix(first[i:], e.member) {
				seq = append(seq, e.groupIdx)
				i += len(e.member)
				found = true
				break
			}
		}
		if !found {
			return 0, false
		}
	}
	// re-match seq at pos
	cur := pos
	for _, gIdx := range seq {
		matched := false
		for _, e := range m.entries {
			if e.groupIdx == gIdx && strings.HasPrefix(text[cur:], e.member) {
				cur += len(e.member)
				matched = true
				break
			}
		}
		if !matched {
			return 0, false
		}
	}
	return cur, true
}

// complementMatcher matches one code point not in any inner group.
type complementMatcher struct {
	innerGroups [][]string
}

func (m *complementMatcher) matchOne(text string, pos int) (int, bool) {
	if pos >= len(text) {
		return 0, false
	}
	_, size := utf8.DecodeRuneInString(text[pos:])
	for _, grp := range m.innerGroups {
		for _, mem := range grp {
			if mem != "" && strings.HasPrefix(text[pos:], mem) {
				return 0, false
			}
		}
	}
	return pos + size, true
}

func (m *complementMatcher) accepts(s string) bool {
	n, ok := m.matchOne(s, 0)
	return ok && n == len(s)
}

func (m *complementMatcher) equalUnit(text string, pos int, first string) (int, bool) {
	n, ok := m.matchOne(text, pos)
	return n, ok
}

// valueMatcher matches a run of alphabet symbols whose positional value is in range.
type valueMatcher struct {
	alph         alphabet
	loVal, hiVal *float64
	wmin         int
	wmax         *int
	excl         *exclusions
}

func (m *valueMatcher) matchOne(text string, pos int) (int, bool) {
	end := pos
	for end < len(text) {
		r, size := utf8.DecodeRuneInString(text[end:])
		if !m.alph.containsRune(r) {
			break
		}
		end += size
	}
	avail := end - pos
	top := avail
	if m.wmax != nil && *m.wmax < top {
		top = *m.wmax
	}
	for w := top; w >= m.wmin; w-- {
		candidate := text[pos : pos+w]
		if m.excl != nil {
			if m.excl.excludesLiteral(candidate) {
				continue
			}
			if w == 1 && m.excl.excludesChar(text, pos) {
				continue
			}
		}
		val, ok := m.alph.value(candidate)
		if !ok {
			continue
		}
		if m.loVal != nil && val < *m.loVal {
			continue
		}
		if m.hiVal != nil && val > *m.hiVal {
			continue
		}
		return pos + w, true
	}
	return 0, false
}

func (m *valueMatcher) accepts(s string) bool {
	n, ok := m.matchOne(s, 0)
	return ok && n == len(s)
}

func (m *valueMatcher) equalUnit(text string, pos int, first string) (int, bool) {
	if strings.HasPrefix(text[pos:], first) {
		return pos + len(first), true
	}
	return 0, false
}

// ---------------------------------------------------------------------------
// Element (prepared VM instruction)
// ---------------------------------------------------------------------------

type element struct {
	op int

	// LIT
	litStr string
	// ANCHOR
	anchorKind int
	// CHAR
	charLo, charHi int
	// GROUP
	groupM *groupMatcher
	// COMPLEMENT
	complementGroups [][]string
	// BACK_REF / COUNT_REF
	refIdx int
	// STAGE_REF
	stageIdx  int
	stagePath []int
	// VALUE_RANGE / DYN_RANGE common
	alph  alphabet
	loVal *float64
	hiVal *float64
	wmin  int
	wmax  *int
	// DYN_RANGE endpoints
	loStatic, hiStatic *string
	loRef, hiRef       *refDesc
	// SEQ_GROUP
	children []*element
	// All reps-bearing opcodes
	excl    *exclusions
	repsVal reps
}

type refDesc struct {
	kind  string // "back", "count", "stage"
	idx   int
	path  []int
}

func parseRefDesc(v any) *refDesc {
	if v == nil {
		return nil
	}
	arr := v.([]any)
	kind := arr[0].(string)
	idx := int(arr[1].(float64))
	var path []int
	if len(arr) > 2 && arr[2] != nil {
		for _, x := range arr[2].([]any) {
			path = append(path, int(x.(float64)))
		}
	}
	return &refDesc{kind: kind, idx: idx, path: path}
}

func optFloat(v any) *float64 {
	if v == nil {
		return nil
	}
	f := v.(float64)
	return &f
}

func optInt(v any) *int {
	if v == nil {
		return nil
	}
	i := int(v.(float64))
	return &i
}

func optStr(v any) *string {
	if v == nil {
		return nil
	}
	s := v.(string)
	return &s
}

func prepareElements(raw []any) ([]*element, error) {
	out := make([]*element, 0, len(raw))
	for _, item := range raw {
		arr := item.([]any)
		op := int(arr[0].(float64))
		el := &element{op: op}

		switch op {
		case opLIT:
			el.litStr = arr[1].(string)

		case opANCHOR:
			el.anchorKind = int(arr[1].(float64))

		case opCHAR:
			// [2, lo, hi, excl, reps]
			el.charLo = int(arr[1].(float64))
			el.charHi = int(arr[2].(float64))
			el.excl = parseExcl(arr[3])
			el.repsVal = parseReps(arr[4])

		case opGROUP:
			// [3, groups_list, het_bool, reps]
			el.groupM = newGroupMatcher(arr[1].([]any))
			el.repsVal = parseReps(arr[3])

		case opBACKREF:
			// [4, group, reps]
			el.refIdx = int(arr[1].(float64))
			el.repsVal = parseReps(arr[2])

		case opCOUNTREF:
			// [5, group, reps]
			el.refIdx = int(arr[1].(float64))
			el.repsVal = parseReps(arr[2])

		case opSTAGEREF:
			// [6, stage, path, reps]
			el.stageIdx = int(arr[1].(float64))
			rawPath := arr[2].([]any)
			el.stagePath = make([]int, len(rawPath))
			for i, x := range rawPath {
				el.stagePath[i] = int(x.(float64))
			}
			el.repsVal = parseReps(arr[3])

		case opVALUERANGE:
			// [7, alph, lo_val, hi_val, wmin, wmax, excl, reps]
			el.alph = parseAlphabet(arr[1])
			el.loVal = optFloat(arr[2])
			el.hiVal = optFloat(arr[3])
			el.wmin = int(arr[4].(float64))
			el.wmax = optInt(arr[5])
			el.excl = parseExcl(arr[6])
			el.repsVal = parseReps(arr[7])

		case opDYNRANGE:
			// [8, alph, lo_static, hi_static, lo_ref, hi_ref, excl, reps]
			el.alph = parseAlphabet(arr[1])
			el.loStatic = optStr(arr[2])
			el.hiStatic = optStr(arr[3])
			el.loRef = parseRefDesc(arr[4])
			el.hiRef = parseRefDesc(arr[5])
			el.excl = parseExcl(arr[6])
			el.repsVal = parseReps(arr[7])

		case opCOMPLEMENT:
			// [10, inner_groups, reps]
			rawGroups := arr[1].([]any)
			grps := make([][]string, len(rawGroups))
			for i, g := range rawGroups {
				members := g.([]any)
				row := make([]string, len(members))
				for j, m := range members {
					row[j] = m.(string)
				}
				grps[i] = row
			}
			el.complementGroups = grps
			el.repsVal = parseReps(arr[2])

		case opSEQGROUP:
			// [11, children, reps]
			children, err := prepareElements(arr[1].([]any))
			if err != nil {
				return nil, err
			}
			el.children = children
			el.repsVal = parseReps(arr[2])

		default:
			return nil, fmt.Errorf("unknown opcode: %d", op)
		}
		out = append(out, el)
	}
	return out, nil
}

// ---------------------------------------------------------------------------
// VM State
// ---------------------------------------------------------------------------

type state struct {
	captures []  *capture
	stages   []*hmatch
	rootLen  int // math.MaxInt when unrestricted; set by outermost SEQ_GROUP
}

func newState(stages []*hmatch) *state {
	return &state{stages: stages, rootLen: math.MaxInt}
}

func (st *state) captureLimit() int {
	if st.rootLen == math.MaxInt {
		return len(st.captures)
	}
	if st.rootLen < len(st.captures) {
		return st.rootLen
	}
	return len(st.captures)
}

// ---------------------------------------------------------------------------
// Reference resolution
// ---------------------------------------------------------------------------

func resolveBack(idx int, st *state, text string) *string {
	lim := st.captureLimit()
	if idx >= lim {
		return nil
	}
	c := st.captures[idx]
	s := text[c.spanStart:c.spanEnd]
	return &s
}

func resolveCount(idx int, st *state) *string {
	lim := st.captureLimit()
	if idx >= lim {
		return nil
	}
	s := fmt.Sprintf("%d", st.captures[idx].repCount())
	return &s
}

func resolveStage(stageIdx int, path []int, st *state) *string {
	if stageIdx < 0 || stageIdx >= len(st.stages) {
		return nil
	}
	m := st.stages[stageIdx]
	if len(path) == 0 {
		return &m.text
	}
	cap := m.captureAt(path)
	if cap == nil {
		return nil
	}
	return &cap.text
}

func resolveRefDescVal(rd *refDesc, st *state, text string) *string {
	switch rd.kind {
	case "back":
		return resolveBack(rd.idx, st, text)
	case "count":
		return resolveCount(rd.idx, st)
	case "stage":
		return resolveStage(rd.idx, rd.path, st)
	}
	return nil
}

// ---------------------------------------------------------------------------
// Push / rollback helper
// ---------------------------------------------------------------------------

func pushCap(st *state, cap *capture, end int, cont func(int) (int, bool)) (int, bool) {
	mark := len(st.captures)
	st.captures = append(st.captures, cap)
	result, ok := cont(end)
	if !ok {
		st.captures = st.captures[:mark]
	}
	return result, ok
}

// ---------------------------------------------------------------------------
// Core VM
// ---------------------------------------------------------------------------

func runProgram(elements []*element, idx int, text string, pos int, st *state) (int, bool) {
	if idx >= len(elements) {
		return pos, true
	}
	e := elements[idx]
	next := idx + 1

	cont := func(end int) (int, bool) {
		return runProgram(elements, next, text, end, st)
	}

	switch e.op {
	case opLIT:
		if strings.HasPrefix(text[pos:], e.litStr) {
			return cont(pos + len(e.litStr))
		}
		return 0, false

	case opANCHOR:
		if checkAnchor(e.anchorKind, text, pos) {
			return cont(pos)
		}
		return 0, false

	case opCHAR:
		r := resolveReps(e.repsVal, st)
		if r == nil {
			return 0, false
		}
		m := &charMatcher{lo: e.charLo, hi: e.charHi, excl: e.excl}
		return runMatcher(m, *r, elements, next, st, text, pos)

	case opGROUP:
		r := resolveReps(e.repsVal, st)
		if r == nil {
			return 0, false
		}
		return runMatcher(e.groupM, *r, elements, next, st, text, pos)

	case opCOMPLEMENT:
		r := resolveReps(e.repsVal, st)
		if r == nil {
			return 0, false
		}
		m := &complementMatcher{innerGroups: e.complementGroups}
		return runMatcher(m, *r, elements, next, st, text, pos)

	case opBACKREF:
		r := resolveReps(e.repsVal, st)
		if r == nil {
			return 0, false
		}
		ref := resolveBack(e.refIdx, st, text)
		return matchReferent(ref, *r, elements, next, text, pos, st)

	case opCOUNTREF:
		r := resolveReps(e.repsVal, st)
		if r == nil {
			return 0, false
		}
		ref := resolveCount(e.refIdx, st)
		return matchReferent(ref, *r, elements, next, text, pos, st)

	case opSTAGEREF:
		r := resolveReps(e.repsVal, st)
		if r == nil {
			return 0, false
		}
		ref := resolveStage(e.stageIdx, e.stagePath, st)
		return matchReferent(ref, *r, elements, next, text, pos, st)

	case opVALUERANGE:
		r := resolveReps(e.repsVal, st)
		if r == nil {
			return 0, false
		}
		m := &valueMatcher{
			alph: e.alph, loVal: e.loVal, hiVal: e.hiVal,
			wmin: e.wmin, wmax: e.wmax, excl: e.excl,
		}
		return runMatcher(m, *r, elements, next, st, text, pos)

	case opDYNRANGE:
		r := resolveReps(e.repsVal, st)
		if r == nil {
			return 0, false
		}
		lower := e.loStatic
		upper := e.hiStatic
		if e.loRef != nil {
			s := resolveRefDescVal(e.loRef, st, text)
			if s == nil {
				return 0, false
			}
			lower = s
		}
		if e.hiRef != nil {
			s := resolveRefDescVal(e.hiRef, st, text)
			if s == nil {
				return 0, false
			}
			upper = s
		}
		m := buildDynMatcher(e.alph, lower, upper, e.excl)
		if m == nil {
			return 0, false
		}
		return runMatcher(m, *r, elements, next, st, text, pos)

	case opSEQGROUP:
		r := resolveReps(e.repsVal, st)
		if r == nil {
			return 0, false
		}
		return matchSeqGroup(e.children, *r, elements, next, text, pos, st)
	}
	return 0, false
}

func checkAnchor(kind int, text string, pos int) bool {
	switch kind {
	case 0: // line start
		return pos == 0 || text[pos-1] == '\n'
	case 1: // line end
		return pos == len(text) || text[pos] == '\n'
	case 2: // doc start
		return pos == 0
	case 3: // doc end
		return pos == len(text)
	}
	return false
}

func buildDynMatcher(alph alphabet, lower, upper *string, excl *exclusions) *valueMatcher {
	var loVal, hiVal *float64
	var wmin int
	var wmax *int

	wf, wc := -1, -1
	if lower != nil {
		v, ok := alph.value(*lower)
		if !ok {
			return nil
		}
		loVal = &v
		wf = len(*lower)
	}
	if upper != nil {
		v, ok := alph.value(*upper)
		if !ok {
			return nil
		}
		hiVal = &v
		wc = len(*upper)
	}
	if wf >= 0 && wc >= 0 {
		if wf < wc {
			wmin = wf
		} else {
			wmin = wc
		}
		mx := wf
		if wc > mx {
			mx = wc
		}
		wmax = &mx
	} else if wf >= 0 {
		wmin = wf
	} else if wc >= 0 {
		wmin = 1
		wmax = &wc
	} else {
		wmin = 1
	}
	return &valueMatcher{alph: alph, loVal: loVal, hiVal: hiVal, wmin: wmin, wmax: wmax, excl: excl}
}

func runMatcher(m matcher, r reps, elements []*element, nextIdx int, st *state, text string, pos int) (int, bool) {
	tryZero := func() (int, bool) {
		if !r.accepts(0) {
			return 0, false
		}
		cap := &capture{spanStart: pos, spanEnd: pos, repsList: nil, count: 0}
		return pushCap(st, cap, pos, func(end int) (int, bool) {
			return runProgram(elements, nextIdx, text, end, st)
		})
	}

	firstEnd, ok := m.matchOne(text, pos)
	if !ok || firstEnd == pos {
		return tryZero()
	}

	for unitLen := firstEnd - pos; unitLen >= 1; unitLen-- {
		first := text[pos : pos+unitLen]
		if !m.accepts(first) {
			continue
		}
		repList := []string{first}
		ends := []int{pos + unitLen}
		cur := pos + unitLen
		for r.max == -1 || len(repList) < r.max {
			nxt, ok2 := m.equalUnit(text, cur, first)
			if !ok2 || nxt <= cur {
				break
			}
			repList = append(repList, text[cur:nxt])
			ends = append(ends, nxt)
			cur = nxt
		}
		for _, k := range counts(r, len(repList)) {
			end := pos
			if k > 0 {
				end = ends[k-1]
			}
			slice := make([]string, k)
			copy(slice, repList[:k])
			cap := &capture{spanStart: pos, spanEnd: end, repsList: slice, count: k}
			if result, ok2 := pushCap(st, cap, end, func(e int) (int, bool) {
				return runProgram(elements, nextIdx, text, e, st)
			}); ok2 {
				return result, true
			}
		}
	}
	return tryZero()
}

func matchReferent(referent *string, r reps, elements []*element, nextIdx int, text string, pos int, st *state) (int, bool) {
	if referent == nil {
		return 0, false
	}
	ref := *referent

	cont := func(end int) (int, bool) {
		return runProgram(elements, nextIdx, text, end, st)
	}

	if ref == "" {
		repsSlice := make([]string, r.min)
		cap := &capture{spanStart: pos, spanEnd: pos, repsList: repsSlice}
		return pushCap(st, cap, pos, cont)
	}

	ends := []int{pos}
	cur := pos
	for (r.max == -1 || len(ends)-1 < r.max) && strings.HasPrefix(text[cur:], ref) {
		cur += len(ref)
		ends = append(ends, cur)
	}
	for _, k := range counts(r, len(ends)-1) {
		end := ends[k]
		slice := make([]string, k)
		for i := range slice {
			slice[i] = ref
		}
		cap := &capture{
			spanStart: pos, spanEnd: end,
			text:     text[pos:end],
			repsList: slice,
		}
		if result, ok := pushCap(st, cap, end, cont); ok {
			return result, true
		}
	}
	return 0, false
}

func matchSeqGroup(children []*element, r reps, elements []*element, nextIdx int, text string, pos int, st *state) (int, bool) {
	prevRootLen := st.rootLen
	if st.rootLen == math.MaxInt {
		st.rootLen = len(st.captures)
	}

	type run struct {
		end  int
		caps []*capture
	}
	var runs []run
	cur := pos

	for r.max == -1 || len(runs) < r.max {
		snapLen := len(st.captures)
		end, ok := runProgram(children, 0, text, cur, st)
		if ok && end > cur {
			subCaps := make([]*capture, len(st.captures)-snapLen)
			copy(subCaps, st.captures[snapLen:])
			st.captures = st.captures[:snapLen]
			runs = append(runs, run{end: end, caps: subCaps})
			cur = end
		} else {
			st.captures = st.captures[:snapLen]
			break
		}
	}

	st.rootLen = prevRootLen

	cont := func(end int) (int, bool) {
		return runProgram(elements, nextIdx, text, end, st)
	}

	for _, k := range counts(r, len(runs)) {
		end := pos
		if k > 0 {
			end = runs[k-1].end
		}
		repTexts := make([]string, k)
		var subs []*capture
		for i := 0; i < k; i++ {
			start := pos
			if i > 0 {
				start = runs[i-1].end
			}
			repTexts[i] = text[start:runs[i].end]
			subs = append(subs, runs[i].caps...)
		}
		cap := &capture{
			text:      text[pos:end],
			spanStart: pos, spanEnd: end,
			repsList: repTexts,
			subs:     subs,
		}
		if result, ok := pushCap(st, cap, end, cont); ok {
			return result, true
		}
	}
	return 0, false
}

// ---------------------------------------------------------------------------
// findMatches / finalize
// ---------------------------------------------------------------------------

func findMatches(elements []*element, text string, stages []*hmatch) []*hmatch {
	var matches []*hmatch
	n := len(text)
	pos := 0
	for pos < n {
		st := newState(stages)
		end, ok := runProgram(elements, 0, text, pos, st)
		if ok && end > pos {
			matches = append(matches, finalize(text, pos, end, st))
			pos = end
		} else {
			pos++
		}
	}
	return matches
}

func finalize(text string, start, end int, st *state) *hmatch {
	var settle func(c *capture)
	settle = func(c *capture) {
		if c.count >= 0 {
			c.repsList = c.repsList[:c.count]
		}
		c.text = text[c.spanStart:c.spanEnd]
		c.spanStart -= start
		c.spanEnd -= start
		for _, s := range c.subs {
			settle(s)
		}
	}
	for _, c := range st.captures {
		settle(c)
	}
	return &hmatch{text: text[start:end], start: start, end: end, captures: st.captures}
}

// ---------------------------------------------------------------------------
// Template
// ---------------------------------------------------------------------------

func indentStr(s string) string {
	if s == "" {
		return ""
	}
	return "\t" + strings.ReplaceAll(s, "\n", "\n\t")
}

func evalExpr(d map[string]any, current string, stages []*hmatch) (string, error) {
	if lit, ok := d["lit"]; ok {
		return fmt.Sprintf("%v", lit), nil
	}
	if _, ok := d["cur"]; ok {
		return current, nil
	}
	if ref, ok := d["ref"]; ok {
		arr := ref.([]any)
		pipeIdx := len(stages) - 1
		if arr[0] != nil {
			pipeIdx = int(arr[0].(float64))
		}
		isCount := false
		if b, ok := arr[1].(bool); ok {
			isCount = b
		}
		if pipeIdx < 0 || pipeIdx >= len(stages) {
			return "", fmt.Errorf("moustache stage %d out of range", pipeIdx)
		}
		sm := stages[pipeIdx]
		if arr[2] == nil {
			return sm.text, nil
		}
		rawPath := arr[2].([]any)
		path := make([]int, len(rawPath))
		for i, x := range rawPath {
			path[i] = int(x.(float64))
		}
		cap := sm.captureAt(path)
		if cap == nil {
			return "", fmt.Errorf("moustache capture %v out of range", path)
		}
		if isCount {
			return fmt.Sprintf("%d", len(cap.repsList)), nil
		}
		return cap.text, nil
	}
	if cat, ok := d["cat"]; ok {
		var sb strings.Builder
		for _, p := range cat.([]any) {
			s, err := evalExpr(p.(map[string]any), current, stages)
			if err != nil {
				return "", err
			}
			sb.WriteString(s)
		}
		return sb.String(), nil
	}
	if name, ok := d["filter"]; ok {
		val, err := evalExpr(d["src"].(map[string]any), current, stages)
		if err != nil {
			return "", err
		}
		switch name.(string) {
		case "trim":
			return strings.TrimSpace(val), nil
		case "indent":
			return indentStr(val), nil
		default:
			return "", fmt.Errorf("unknown template filter: %q", name)
		}
	}
	return "", fmt.Errorf("unknown expression node: %v", d)
}

type span struct{ start, end int }

func renderTemplate(parts []any, current string, stages []*hmatch) (string, []span, error) {
	var out strings.Builder
	var spans []span
	pos := 0
	for _, p := range parts {
		switch v := p.(type) {
		case string:
			out.WriteString(v)
			pos += len(v)
		case map[string]any:
			val, err := evalExpr(v, current, stages)
			if err != nil {
				return "", nil, err
			}
			spans = append(spans, span{pos, pos + len(val)})
			out.WriteString(val)
			pos += len(val)
		default:
			return "", nil, fmt.Errorf("unexpected template part type: %T", p)
		}
	}
	full := out.String()
	if len(spans) == 0 {
		return full, nil, nil
	}
	return full, spans, nil
}

// ---------------------------------------------------------------------------
// Steps
// ---------------------------------------------------------------------------

type step interface{ fixedPoint() bool }

type programStep struct {
	elements   []*element
	groups     int
	fixedPt    bool
}

func (p *programStep) fixedPoint() bool { return p.fixedPt }

type templateStep struct {
	parts   []any
	fixedPt bool
}

func (t *templateStep) fixedPoint() bool { return t.fixedPt }

func jsonToStep(d map[string]any) (step, error) {
	kind, _ := d["kind"].(string)
	fp, _ := d["fixed_point"].(bool)
	switch kind {
	case "program", "query":
		rawEls, _ := d["elements"].([]any)
		els, err := prepareElements(rawEls)
		if err != nil {
			return nil, err
		}
		groups := 0
		if g, ok := d["groups"].(float64); ok {
			groups = int(g)
		}
		return &programStep{elements: els, groups: groups, fixedPt: fp}, nil

	case "template":
		rawParts, _ := d["template"].([]any)
		parts := make([]any, len(rawParts))
		for i, p := range rawParts {
			switch v := p.(type) {
			case string:
				parts[i] = v
			case map[string]any:
				// {"m": expr}
				if m, ok := v["m"]; ok {
					parts[i] = m.(map[string]any)
				} else {
					parts[i] = v
				}
			}
		}
		return &templateStep{parts: parts, fixedPt: fp}, nil
	}
	return nil, fmt.Errorf("unknown step kind: %q", kind)
}

// ---------------------------------------------------------------------------
// Pipeline execution
// ---------------------------------------------------------------------------

type delta struct{ start, end int; text string }

func transform(steps []step, text string, ancestors []*hmatch, committed bool) (string, bool, error) {
	if len(steps) == 0 {
		return text, true, nil
	}
	head := steps[0]
	rest := steps[1:]

	if t, ok := head.(*templateStep); ok {
		full, spans, err := renderTemplate(t.parts, text, ancestors)
		if err != nil {
			return "", false, err
		}
		if spans == nil {
			stage := &hmatch{text: full, start: 0, end: len(full)}
			return transform(rest, full, append(ancestors, stage), true)
		}
		if len(rest) == 0 {
			return full, true, nil
		}
		var pieces []string
		last := 0
		for _, sp := range spans {
			payload := full[sp.start:sp.end]
			stage := &hmatch{text: payload, start: 0, end: len(payload)}
			sub, ok, err := transform(rest, payload, append(ancestors, stage), true)
			if err != nil {
				return "", false, err
			}
			if !ok {
				return "", false, nil
			}
			pieces = append(pieces, full[last:sp.start], sub)
			last = sp.end
		}
		pieces = append(pieces, full[last:])
		return strings.Join(pieces, ""), true, nil
	}

	prog := head.(*programStep)
	matches := findMatches(prog.elements, text, ancestors)
	if len(matches) == 0 {
		if committed {
			return text, true, nil
		}
		return "", false, nil
	}
	var pieces []string
	last := 0
	for _, m := range matches {
		sub, ok, err := transform(rest, m.text, append(ancestors, m), committed)
		if err != nil {
			return "", false, err
		}
		if !ok {
			return "", false, nil
		}
		pieces = append(pieces, text[last:m.start], sub)
		last = m.end
	}
	pieces = append(pieces, text[last:])
	return strings.Join(pieces, ""), true, nil
}

func computeDeltas(steps []step, target string) ([]delta, error) {
	if len(steps) == 0 {
		return nil, nil
	}
	head := steps[0]
	if _, ok := head.(*templateStep); ok {
		result, ok2, err := transform(steps, target, nil, false)
		if err != nil {
			return nil, err
		}
		if !ok2 {
			return nil, nil
		}
		return []delta{{0, len(target), result}}, nil
	}
	prog := head.(*programStep)
	rest := steps[1:]
	matches := findMatches(prog.elements, target, nil)
	var out []delta
	for _, m := range matches {
		result, ok, err := transform(rest, m.text, []*hmatch{m}, false)
		if err != nil {
			return nil, err
		}
		if ok {
			out = append(out, delta{m.start, m.end, result})
		}
	}
	return out, nil
}

func splice(steps []step, target string) (string, error) {
	deltas, err := computeDeltas(steps, target)
	if err != nil {
		return "", err
	}
	var pieces []string
	last := 0
	for _, d := range deltas {
		pieces = append(pieces, target[last:d.start], d.text)
		last = d.end
	}
	pieces = append(pieces, target[last:])
	return strings.Join(pieces, ""), nil
}

func spliceToFixedPoint(steps []step, target string) (string, error) {
	text := target
	cap := 8*len(target) + 1024
	sizeLimit := 64*len(target) + 65536
	for i := 0; i < cap; i++ {
		result, err := splice(steps, text)
		if err != nil {
			return "", err
		}
		if result == text {
			return text, nil
		}
		text = result
		if len(text) > sizeLimit {
			break
		}
	}
	return "", fmt.Errorf("a `<=>` statement did not settle -- the rule is not contracting toward a fixed point (it grows or oscillates). Use `=>` for a single pass.")
}

func runPipeline(pipeline [][]map[string]any, target string) (string, error) {
	result := target
	for _, stmtJSON := range pipeline {
		if len(stmtJSON) == 0 {
			continue
		}
		steps := make([]step, 0, len(stmtJSON))
		for _, sj := range stmtJSON {
			s, err := jsonToStep(sj)
			if err != nil {
				return "", err
			}
			steps = append(steps, s)
		}
		var err error
		if steps[0].fixedPoint() {
			result, err = spliceToFixedPoint(steps, result)
		} else {
			result, err = splice(steps, result)
		}
		if err != nil {
			return "", err
		}
	}
	return result, nil
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

func writeError(msg string) {
	out, _ := json.Marshal(map[string]string{"error": msg})
	os.Stdout.Write(out)
	os.Stdout.Write([]byte("\n"))
}

func main() {
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		writeError(fmt.Sprintf("failed to read stdin: %v", err))
		os.Exit(1)
	}

	var payload struct {
		Pipeline [][]map[string]any `json:"pipeline"`
		Target   string             `json:"target"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		writeError(fmt.Sprintf("JSON parse error: %v", err))
		os.Exit(1)
	}

	result, err := runPipeline(payload.Pipeline, payload.Target)
	if err != nil {
		writeError(err.Error())
		os.Exit(1)
	}
	out, _ := json.Marshal(map[string]string{"result": result})
	os.Stdout.Write(out)
	os.Stdout.Write([]byte("\n"))
}
