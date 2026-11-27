package main

import (
	"bytes"
	"flag"
	"fmt"
	"log"
	"os"
	"strconv"

	lifecycle "github.com/mohanraj00/entelos/src/lifecycle-core"
)

// The test runner passes the content manifest that the Host gives it. If
// measure is not nil, the runner gives it as the measure summary.
type fixtureRunner struct{ measure any }

func (*fixtureRunner) Identity() (string, error) {
	return lifecycle.ContentRef([]byte("calibration fixture runner")), nil
}

func (r *fixtureRunner) Expected(lifecycle.Candidate) string {
	return must(r.Identity())
}

func (r *fixtureRunner) Qualify(in lifecycle.QualificationInput) (lifecycle.Verdict, error) {
	return lifecycle.Verdict{Outcome: lifecycle.Object{
		"status": "passed", "bundle_ref": lifecycle.ContentRef(in.Files["content"]),
		"implementation_ref": r.Expected(in.Candidate),
	}, Measure: r.measure}, nil
}

func must[T any](value T, err error) T {
	if err != nil {
		log.Fatal(err)
	}
	return value
}

const from, until = "2026-11-01", "2026-12-01"

type writeFunc func(actor, role, op string, body lifecycle.Object) lifecycle.Object

// newHost gives a Host on an empty store, and a function that sends one write
// to it.
func newHost(runner lifecycle.Runner, context lifecycle.Object) (*lifecycle.Host, writeFunc) {
	store := lifecycle.NewMemoryStore()
	host := must(lifecycle.NewHostWithRunner(store, nil, runner, context))
	requests := 0
	return host, func(actor, role, op string, body lifecycle.Object) lifecycle.Object {
		requests++
		body["op"] = op
		body["expected_revision"] = must(store.Read(nil)).Cursor
		body["request_key"] = fmt.Sprintf("seam-%d", requests)
		response, err := host.HandleAs(actor, []string{role}, body)
		if err != nil {
			log.Fatalf("%s failed with %v", op, err)
		}
		return response.(lifecycle.Object)["result"].(lifecycle.Object)
	}
}

func decisions(evidence lifecycle.Object) []byte {
	const subject = "content:invoice/seam"
	host, write := newHost(&fixtureRunner{}, lifecycle.Object{
		"scope": "invoice", "functions": lifecycle.Array{subject}, "runner_actor": "runner",
		"worker": "worker", "actor_kinds": lifecycle.Object{"reviewer": "human", "rules": "policy"},
	})
	source := write("reviewer", "reviewer", "source", lifecycle.Object{
		"function": subject, "from": from, "until": until, "text": "Review the invoice facts.",
		"reason": "Test calibration events.",
	})
	plan := write("reviewer", "reviewer", "plan", lifecycle.Object{
		"source_ref": source["source_ref"], "cases": lifecycle.Array{lifecycle.Object{"case": "invoice"}},
		"origin": "test fixture",
	})

	base := ""
	review := func(fact any, actor string, verdict lifecycle.Object) {
		manifest := lifecycle.Encode(lifecycle.Object{
			"format": "entelos.content/1", "collection": "invoice", "partition": "seam", "base": base,
			"items": lifecycle.Array{lifecycle.Object{
				"item_id": "invoice", "digest": lifecycle.ContentRef([]byte("invoice")),
				"size": 7, "media_type": "text/plain",
			}},
		})
		proposal := write("producer", "author", "propose", lifecycle.Object{
			"candidate":  lifecycle.Object{"kind": "content", "manifest": string(manifest)},
			"source_ref": source["source_ref"], "from": from, "until": until,
			"reason": "Review one fact.", "evidence": lifecycle.Object{
				"format": evidence["format"], "producer": evidence["producer"], "facts": lifecycle.Array{fact},
			},
		})
		base = proposal["candidate"].(lifecycle.Object)["ref"].(string)
		report := write("runner", "runner", "qualify", lifecycle.Object{
			"snapshot_ref": proposal["snapshot_ref"], "plan_ref": plan["plan_ref"],
		})
		verdict["report_ref"] = report["report_ref"]
		verdict["reason"] = "Record the test decision."
		write(actor, "reviewer", "decide", verdict)
	}

	facts := evidence["facts"].(lifecycle.Array)
	if len(facts) != 3 {
		log.Fatal("The evidence must have three facts.")
	}
	review(facts[0], "rules", lifecycle.Object{"disposition": "accept"})
	review(facts[1], "reviewer", lifecycle.Object{
		"disposition": "reject", "fact_reviews": lifecycle.Array{lifecycle.Object{"blind": false}},
	})
	review(facts[2], "reviewer", lifecycle.Object{
		"disposition": "accept", "fact_reviews": lifecycle.Array{lifecycle.Object{"blind": false, "corrected_value": "95"}},
	})

	page := must(host.HandleAs("reader", []string{"event_reader"}, lifecycle.Object{
		"op": "decision_events", "limit": 256,
	})).(lifecycle.Object)
	var output bytes.Buffer
	for _, event := range page["events"].(lifecycle.Array) {
		if check := lifecycle.CheckDecisionEvent(event); check["valid"] != true {
			log.Fatalf("The decision event failed rule %v with code %v.", check["rule"], check["code"])
		}
		output.Write(lifecycle.Encode(event))
	}
	return output.Bytes()
}

// promotions proposes each promotion of the input as one version of one
// profile, in the input order. The input has the limit of the policy in basis
// points, and the manifest text and the measure summary of each promotion, as
// groundgate wrote them.
//
// No Host of this release writes a policy verdict. Thus the actor "rules", of
// the kind policy, applies the limit to the inputs of the promotion read and
// records its verdict with decide. The output has one line for each
// promotion: the candidate reference, the promotion read, the stored measure
// summary and the stored decision.
func promotions(input lifecycle.Object) []byte {
	limit := must(strconv.Atoi(input["limit"].(lifecycle.Int).Text))
	list := input["promotions"].(lifecycle.Array)
	first := must(lifecycle.Decode([]byte(list[0].(lifecycle.Object)["manifest"].(string)))).(lifecycle.Object)
	collection := first["collection"].(string)
	subject := "content:" + collection + "/" + first["partition"].(string)
	runner := &fixtureRunner{}
	host, write := newHost(runner, lifecycle.Object{
		"scope": "profiles", "functions": lifecycle.Array{subject}, "runner_actor": "runner",
		"worker": "worker", "actor_kinds": lifecycle.Object{"rules": "policy"},
		"promotion_collections": lifecycle.Array{collection},
	})
	read := func(body lifecycle.Object) lifecycle.Object {
		return must(host.HandleAs("rules", []string{"reviewer"}, body)).(lifecycle.Object)
	}
	source := write("reviewer", "reviewer", "source", lifecycle.Object{
		"function": subject, "from": from, "until": until, "text": "Promote a measured profile.",
		"reason": "Test the profile promotion.",
	})
	plan := write("reviewer", "reviewer", "plan", lifecycle.Object{
		"source_ref": source["source_ref"], "cases": lifecycle.Array{lifecycle.Object{"case": "measure"}},
		"origin": "test fixture",
	})

	var output bytes.Buffer
	for _, x := range list {
		promotion := x.(lifecycle.Object)
		proposal := write("producer", "author", "propose", lifecycle.Object{
			"candidate":  lifecycle.Object{"kind": "content", "manifest": promotion["manifest"]},
			"source_ref": source["source_ref"], "from": from, "until": until,
			"reason": "Promote one profile version.",
		})
		runner.measure = promotion["summary"]
		report := write("runner", "runner", "qualify", lifecycle.Object{
			"snapshot_ref": proposal["snapshot_ref"], "plan_ref": plan["plan_ref"],
		})
		result := read(lifecycle.Object{"op": "promotion", "report_ref": report["report_ref"]})
		if result["promotion"] != "valid" {
			log.Fatalf("The promotion read failed rule %v.", result["rule"])
		}
		inputs := result["inputs"].(lifecycle.Object)
		largest := must(strconv.Atoi(inputs["measure_max_bound_bp"].(lifecycle.Int).Text))
		verdict := lifecycle.Object{"report_ref": report["report_ref"], "disposition": "accept",
			"reason": fmt.Sprintf("Each bound is in the limit of %d basis points.", limit)}
		if largest > limit {
			verdict["disposition"] = "reject"
			verdict["reason"] = fmt.Sprintf("The largest bound, %d basis points, is above the limit of %d.", largest, limit)
		}
		decision := write("rules", "reviewer", "decide", verdict)
		stored := read(lifecycle.Object{"op": "record", "ref": report["report_ref"], "kind": "qualification"})
		output.Write(lifecycle.Encode(lifecycle.Object{
			"candidate_ref": proposal["candidate"].(lifecycle.Object)["ref"],
			"read":          result, "summary": stored["measure"],
			"decision": read(lifecycle.Object{"op": "record", "ref": decision["decision_ref"], "kind": "decision"}),
		}))
	}
	return output.Bytes()
}

func main() {
	log.SetFlags(0)
	evidence := flag.String("evidence", "", "File with three cited facts")
	promote := flag.String("promotions", "", "File with a limit and the promotions")
	out := flag.String("out", "", "File for the decision events, or for the promotion results")
	flag.Parse()
	if (*evidence == "") == (*promote == "") || *out == "" {
		log.Fatal("Set -evidence or -promotions, and -out.")
	}
	input := must(lifecycle.Decode(must(os.ReadFile(*evidence + *promote)))).(lifecycle.Object)
	run := decisions
	if *promote != "" {
		run = promotions
	}
	if err := os.WriteFile(*out, run(input), 0o600); err != nil {
		log.Fatal(err)
	}
}
