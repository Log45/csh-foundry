import java.io.File;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.formats.RDFXMLDocumentFormat;
import org.semanticweb.owlapi.formats.TurtleDocumentFormat;
import org.semanticweb.owlapi.formats.OWLXMLDocumentFormat;
import org.semanticweb.owlapi.model.*;

/** Uses the exact OWLAPI version selected by Protégé 5.6.9's pom.xml. */
public class CompatibilityCheck {
    public static void main(String[] args) throws Exception {
        OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
        OWLOntology ontology = manager.loadOntologyFromOntologyDocument(new File(args[0]));
        if (args.length == 3 && args[2].equals("interchange")) {
            File directory = new File(args[1]);
            directory.mkdirs();
            OWLDocumentFormat[] formats = {new TurtleDocumentFormat(), new RDFXMLDocumentFormat(),
                    new OWLXMLDocumentFormat()};
            String[] names = {"roundtrip.ttl", "roundtrip.rdf", "roundtrip.owx"};
            for (int i = 0; i < formats.length; i++) {
                File target = new File(directory, names[i]);
                manager.saveOntology(ontology, formats[i], IRI.create(target));
                OWLOntology loaded = OWLManager.createOWLOntologyManager()
                        .loadOntologyFromOntologyDocument(target);
                java.util.Set<OWLAxiom> lost = new java.util.HashSet<>(ontology.getAxioms());
                lost.removeAll(loaded.getAxioms());
                java.util.Set<OWLAxiom> added = new java.util.HashSet<>(loaded.getAxioms());
                added.removeAll(ontology.getAxioms());
                OWLAxiom date = manager.getOWLDataFactory().getOWLDeclarationAxiom(
                        manager.getOWLDataFactory().getOWLDatatype(
                                IRI.create("http://www.w3.org/2001/XMLSchema#date")));
                added.remove(date);
                if (!lost.isEmpty() || !added.isEmpty()
                        || !ontology.getOntologyID().equals(loaded.getOntologyID())) {
                    throw new IllegalStateException("Unexpected axiom/ontology/version change in "
                            + names[i] + ": lost=" + lost + "; added=" + added);
                }
                System.out.println("PASS OWLAPI 4.5.29 " + names[i]
                        + ": ontology/version identity and all source axioms retained");
            }
            System.out.println("NOTE platform accepts Turtle and RDF/XML only; OWL/XML is OWLAPI-only");
            return;
        }
        if (ontology.getClassesInSignature().size() != 5
                || ontology.getDataPropertiesInSignature().size() != 13
                || ontology.getObjectPropertiesInSignature().size() != 6
                || ontology.getAxiomCount(AxiomType.HAS_KEY) != 4
                || ontology.getAxiomCount(AxiomType.INVERSE_OBJECT_PROPERTIES) != 3
                || ontology.getAxiomCount(AxiomType.EQUIVALENT_CLASSES) != 1) {
            throw new IllegalStateException("Fixture signature/axioms differ");
        }
        File output = new File(args[1]);
        output.getParentFile().mkdirs();
        manager.saveOntology(ontology, new RDFXMLDocumentFormat(), IRI.create(output));
        OWLOntology reloaded = OWLManager.createOWLOntologyManager().loadOntologyFromOntologyDocument(output);
        java.util.Set<OWLAxiom> removed = new java.util.HashSet<>(ontology.getAxioms());
        removed.removeAll(reloaded.getAxioms());
        java.util.Set<OWLAxiom> added = new java.util.HashSet<>(reloaded.getAxioms());
        added.removeAll(ontology.getAxioms());
        OWLAxiom dateDeclaration = manager.getOWLDataFactory().getOWLDeclarationAxiom(
            manager.getOWLDataFactory().getOWLDatatype(IRI.create("http://www.w3.org/2001/XMLSchema#date")));
        if (!removed.isEmpty() || !added.equals(java.util.Collections.singleton(dateDeclaration))) {
            throw new IllegalStateException("Unexpected roundtrip changes: removed=" + removed + "; added=" + added);
        }
        System.out.println("NOTE OWLAPI serialization adds Declaration(Datatype(xsd:date)); no axioms removed");
        System.out.println("PASS OWLAPI 4.5.29: 5 classes, 13 data properties, 6 object properties, "
                + "4 keys, 3 inverses, 1 equivalent class; RDF/XML roundtrip with explicit xsd:date declaration");
    }
}
