# OWLAPI interoperability fixture

`manufacturing-rdfxml.owl` was generated from the unchanged `fixtures/manufacturing.ttl` using the
pinned Protégé 5.6.9-compatible OWLAPI 4.5.29 harness during the Phase 6 baseline. This is a verified
OWLAPI-generated artifact, **not** claimed to have been saved in the Protégé GUI.

All source OWL axioms and ontology/version IRIs survive. OWLAPI adds xsd:date's datatype declaration,
may reverse symmetric inverse-property axioms, reorders lists/statements and serializes explicit
xsd:string as RDF 1.1 simple literals. Tests record raw graph differences and compare those exact
serialization conventions explicitly in memory; original source bytes are never rewritten.

Reproduce default compatibility check:

```sh
mvn -q -f integrations/protege/pom.xml compile exec:java \
  '-Dexec.args=fixtures/manufacturing.ttl artifacts/manufacturing.owl'
```

Extended harness checks Turtle, RDF/XML and OWL/XML axiom/ontology/version retention:

```sh
mvn -q -f integrations/protege/pom.xml compile exec:java \
  '-Dexec.args=fixtures/manufacturing.ttl artifacts/phase6-interchange interchange'
```

The Python platform accepts Turtle and RDF/XML only. OWL/XML requires an external conversion.
