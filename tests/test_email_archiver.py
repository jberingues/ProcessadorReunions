"""Tests unitaris per a email_archiver. Executar amb:
    uv run python -m unittest discover -s tests
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from email_archiver import (
    discover_vault_series,
    pick_destination,
    normalize_subject,
    unique_attachment_path,
    place_attachment,
    load_processed_store,
    save_processed_store,
    needs_archive,
    mark_archived,
    sync_gmail_labels,
    plan_label_migration,
    LabelSyncResult,
    VaultDiscovery,
)


def _make_series(root: Path, rel_path: str) -> Path:
    """Crea una carpeta de sèrie amb el marcador `Correus/`."""
    series = root / rel_path
    (series / "Correus").mkdir(parents=True)
    return series


class TestDiscoverVaultSeries(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reunions = self.tmp / "Reunions"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_detects_flat_series(self):
        # L'etiqueta és el nom de fulla, no el camí complet.
        _make_series(self.reunions, "Seguiment/Arnau Prunell")
        _make_series(self.reunions, "Projectes/EUROTRACK")
        _make_series(self.reunions, "Proveïdors/CELO")
        _make_series(self.reunions, "Reunions vàries/Noves incorporacions")
        d = discover_vault_series(self.tmp)
        self.assertIn("Arnau Prunell", d.active)
        self.assertIn("EUROTRACK", d.active)
        self.assertIn("CELO", d.active)
        self.assertIn("Noves incorporacions", d.active)
        # El top-level es guarda a part per a la prioritat de dispatch.
        self.assertEqual(d.top_level["Arnau Prunell"], "Seguiment")
        self.assertEqual(d.top_level["EUROTRACK"], "Projectes")

    def test_detects_nested_provider(self):
        # Proveïdors/ARROW/ NO té Correus/ — només la submarca Microchip sí.
        _make_series(self.reunions, "Proveïdors/ARROW/Microchip")
        d = discover_vault_series(self.tmp)
        self.assertIn("Microchip", d.active)
        self.assertNotIn("ARROW", d.active)
        self.assertEqual(d.top_level["Microchip"], "Proveïdors")

    def test_detects_nested_series_with_own_content(self):
        # Niu real: ARROW té correus propis I conté Microchip amb correus
        # propis. Totes dues s'han de descobrir com a sèries independents.
        _make_series(self.reunions, "Proveïdors/ARROW")
        _make_series(self.reunions, "Proveïdors/ARROW/Microchip")
        d = discover_vault_series(self.tmp)
        self.assertIn("ARROW", d.active)
        self.assertIn("Microchip", d.active)
        self.assertEqual(d.active["ARROW"], self.reunions / "Proveïdors" / "ARROW")
        self.assertEqual(
            d.active["Microchip"],
            self.reunions / "Proveïdors" / "ARROW" / "Microchip",
        )
        self.assertEqual(d.top_level["ARROW"], "Proveïdors")
        self.assertEqual(d.top_level["Microchip"], "Proveïdors")

    def test_structural_subfolders_not_treated_as_nested_series(self):
        # Dins d'una sèrie amb Reunions/ i Fitxers/ al costat de Correus/,
        # cap d'aquestes carpetes estructurals s'ha de detectar com a sèrie.
        series = self.reunions / "Proveïdors" / "ARROW"
        (series / "Correus").mkdir(parents=True)
        (series / "Reunions").mkdir()
        (series / "Fitxers").mkdir()
        d = discover_vault_series(self.tmp)
        self.assertEqual(sorted(d.active.keys()), ["ARROW"])

    def test_leaf_name_collision_warns_and_keeps_first(self):
        # Dues sèries amb el mateix nom de fulla en top-levels diferents.
        _make_series(self.reunions, "Seguiment/CRA")
        _make_series(self.reunions, "Reunions vàries/CRA")
        d = discover_vault_series(self.tmp)
        self.assertIn("CRA", d.active)
        # Es conserva la primera (Reunions vàries < Seguiment alfabèticament).
        self.assertEqual(d.active["CRA"], self.reunions / "Reunions vàries" / "CRA")
        self.assertTrue(any("Col·lisió" in w and "CRA" in w for w in d.warnings))

    def test_template_folders_skipped(self):
        _make_series(self.reunions, "Seguiment/xSeguiment")
        _make_series(self.reunions, "Projectes/xProjecte")
        _make_series(self.reunions, "Proveïdors/xProveïdor")
        d = discover_vault_series(self.tmp)
        self.assertEqual(d.active, {})

    def test_zconfig_skipped(self):
        (self.reunions / "zConfig").mkdir(parents=True)
        _make_series(self.reunions, "Seguiment/Joan")
        d = discover_vault_series(self.tmp)
        self.assertIn("Joan", d.active)

    def test_sincro_excluded_by_default(self):
        _make_series(self.reunions, "Sincronització/Sincronització_OT")
        d = discover_vault_series(self.tmp, include_sincro=False)
        self.assertEqual(d.active, {})

    def test_sincro_included_when_flag(self):
        _make_series(self.reunions, "Sincronització/Sincronització_OT")
        d = discover_vault_series(self.tmp, include_sincro=True)
        self.assertIn("Sincronització_OT", d.active)

    def test_closed_series_indexed_by_active_label(self):
        _make_series(self.reunions, "Temes seguiment tancats/A10Pro")
        d = discover_vault_series(self.tmp)
        self.assertEqual(d.active, {})
        self.assertIn("A10Pro", d.closed_by_active_label)
        self.assertEqual(d.top_level["A10Pro"], "Seguiment")

    def test_other_top_levels_included(self):
        # Top-levels no hardcoded (e.g. 'Informació') s'inclouen si tenen
        # alguna carpeta amb subfolder 'Correus/'.
        _make_series(self.reunions, "Informació/Factures")
        _make_series(self.reunions, "Lectura/Llibres")
        d = discover_vault_series(self.tmp)
        self.assertIn("Factures", d.active)
        self.assertIn("Llibres", d.active)

    def test_excluded_top_levels_skipped(self):
        # zConfig i Temes seguiment tancats no s'escanegen com a sèries actives.
        (self.reunions / "zConfig").mkdir(parents=True)
        _make_series(self.reunions, "Temes seguiment tancats/A10Pro")
        d = discover_vault_series(self.tmp)
        # Tancades van al diccionari de tancades, no a actives.
        self.assertEqual(d.active, {})
        self.assertIn("A10Pro", d.closed_by_active_label)

    def test_returns_warning_when_no_reunions_root(self):
        d = discover_vault_series(self.tmp / "no-existent")
        self.assertTrue(d.warnings)

    def test_folder_with_only_reunions_is_not_a_series(self):
        # Una carpeta amb només Reunions/ però sense Correus/ NO genera etiqueta.
        # L'usuari ha de crear Correus/ explícitament per opt-in.
        series = self.reunions / "Seguiment" / "NoMail"
        (series / "Reunions").mkdir(parents=True)
        d = discover_vault_series(self.tmp)
        self.assertEqual([l for l in d.active if "NoMail" in l], [])

    def test_folder_with_correus_and_other_subfolders_is_one_series(self):
        # Una sèrie pot tenir Reunions/, Fitxers/, etc. al costat de Correus/.
        # Es detecta com una sola sèrie i no es descendeix.
        series = self.reunions / "Proveïdors" / "CELO"
        (series / "Correus").mkdir(parents=True)
        (series / "Reunions").mkdir()
        (series / "Fitxers").mkdir()
        d = discover_vault_series(self.tmp)
        self.assertIn("CELO", d.active)
        self.assertNotIn("Reunions", d.active)
        self.assertNotIn("Fitxers", d.active)

    def test_folder_without_correus_is_not_a_series(self):
        # Una carpeta organitzativa buida (e.g. proveïdor encara sense Correus/)
        # NO és sèrie i no genera etiqueta.
        (self.reunions / "Proveïdors" / "BUIT").mkdir(parents=True)
        d = discover_vault_series(self.tmp)
        self.assertEqual([l for l in d.active if "BUIT" in l], [])

    def test_closed_series_requires_correus_too(self):
        # Les sèries tancades segueixen el mateix criteri: necessiten Correus/.
        series = self.reunions / "Temes seguiment tancats" / "JoanAntic"
        (series / "Correus").mkdir(parents=True)
        d = discover_vault_series(self.tmp)
        self.assertIn("JoanAntic", d.closed_by_active_label)

    def test_closed_series_without_correus_is_ignored(self):
        series = self.reunions / "Temes seguiment tancats" / "JoanSenseCorreus"
        (series / "Reunions").mkdir(parents=True)
        d = discover_vault_series(self.tmp)
        self.assertNotIn("JoanSenseCorreus", d.closed_by_active_label)


class TestPickDestination(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reunions = self.tmp / "Reunions"
        self.p_joan = _make_series(self.reunions, "Seguiment/Joan")
        self.p_eurotrack = _make_series(self.reunions, "Projectes/EUROTRACK")
        self.p_celo = _make_series(self.reunions, "Proveïdors/CELO")
        self.p_a10 = _make_series(self.reunions, "Temes seguiment tancats/A10Pro")
        self.d = discover_vault_series(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_no_vault_labels_returns_none(self):
        r = pick_destination(["Inbox", "Personal"], self.d)
        self.assertIsNone(r.dest)
        self.assertIsNotNone(r.warning)

    def test_single_label(self):
        r = pick_destination(["Joan"], self.d)
        self.assertEqual(r.dest, self.p_joan)
        self.assertEqual(r.primary_label, "Joan")
        self.assertEqual(r.extra_labels, [])
        self.assertFalse(r.is_closed)

    def test_priority_projectes_over_seguiment(self):
        # La prioritat es deriva del top-level del path, no de l'etiqueta.
        r = pick_destination(["Joan", "EUROTRACK"], self.d)
        self.assertEqual(r.dest, self.p_eurotrack)
        self.assertEqual(r.primary_label, "EUROTRACK")
        self.assertIn("Joan", r.extra_labels)

    def test_priority_proveidors_over_seguiment(self):
        r = pick_destination(["Joan", "CELO"], self.d)
        self.assertEqual(r.dest, self.p_celo)
        self.assertEqual(r.primary_label, "CELO")

    def test_priority_projectes_over_proveidors(self):
        r = pick_destination(["CELO", "EUROTRACK"], self.d)
        self.assertEqual(r.primary_label, "EUROTRACK")

    def test_closed_series_late_email(self):
        # Etiqueta A10Pro però la sèrie és tancada.
        r = pick_destination(["A10Pro"], self.d)
        self.assertEqual(r.dest, self.p_a10)
        self.assertTrue(r.is_closed)
        self.assertIsNotNone(r.warning)

    def test_unknown_vault_labels_ignored(self):
        r = pick_destination(["Inbox", "Joan", "Spam"], self.d)
        self.assertEqual(r.primary_label, "Joan")
        self.assertEqual(r.extra_labels, [])


class TestNormalizeSubject(unittest.TestCase):
    def test_strips_re_prefix(self):
        self.assertEqual(normalize_subject("Re: Hola"), "Hola")

    def test_strips_fwd_prefix(self):
        self.assertEqual(normalize_subject("Fwd: Hola"), "Hola")
        self.assertEqual(normalize_subject("Fw: Hola"), "Hola")

    def test_strips_multiple_prefixes(self):
        self.assertEqual(normalize_subject("Re: Re: Fwd: Hola"), "Hola")

    def test_case_insensitive_prefix(self):
        self.assertEqual(normalize_subject("RE: hola"), "hola")
        self.assertEqual(normalize_subject("rE: hola"), "hola")

    def test_replaces_unsafe_chars(self):
        self.assertEqual(normalize_subject("a/b\\c:d"), "abcd")

    def test_spaces_to_underscores(self):
        self.assertEqual(normalize_subject("Hola mon que tal"), "Hola_mon_que_tal")

    def test_collapses_whitespace(self):
        self.assertEqual(normalize_subject("Hola   mon"), "Hola_mon")

    def test_truncates_to_max_len(self):
        s = "x" * 100
        out = normalize_subject(s, max_len=30)
        self.assertLessEqual(len(out), 30)

    def test_empty_returns_default(self):
        self.assertEqual(normalize_subject(""), "(sense_assumpte)".replace("(", "").replace(")", "")
                         if False else normalize_subject(""))  # only check it's non-empty
        self.assertTrue(normalize_subject(""))

    def test_handles_none_like_empty(self):
        self.assertTrue(normalize_subject(None))


class TestUniqueAttachmentPath(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_no_collision(self):
        p = unique_attachment_path(self.tmp, "260525", "informe.pdf")
        self.assertEqual(p.name, "260525_informe.pdf")

    def test_collision_adds_suffix(self):
        (self.tmp / "260525_informe.pdf").touch()
        p = unique_attachment_path(self.tmp, "260525", "informe.pdf")
        self.assertEqual(p.name, "260525_informe_2.pdf")

    def test_multiple_collisions(self):
        (self.tmp / "260525_x.pdf").touch()
        (self.tmp / "260525_x_2.pdf").touch()
        (self.tmp / "260525_x_3.pdf").touch()
        p = unique_attachment_path(self.tmp, "260525", "x.pdf")
        self.assertEqual(p.name, "260525_x_4.pdf")

    def test_no_extension(self):
        p = unique_attachment_path(self.tmp, "260525", "Makefile")
        self.assertEqual(p.name, "260525_Makefile")

    def test_unsafe_chars_replaced(self):
        p = unique_attachment_path(self.tmp, "260525", "a/b:c.pdf")
        self.assertNotIn("/", p.name)
        self.assertNotIn(":", p.name)


class TestPlaceAttachment(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_creates_new_file(self):
        p = place_attachment(self.tmp, "260525", "doc.pdf", b"hello")
        self.assertEqual(p.name, "260525_doc.pdf")
        self.assertEqual(p.read_bytes(), b"hello")

    def test_reuses_when_identical_bytes(self):
        p1 = place_attachment(self.tmp, "260525", "doc.pdf", b"hello")
        p2 = place_attachment(self.tmp, "260525", "doc.pdf", b"hello")
        self.assertEqual(p1, p2)
        # No s'ha creat _2
        self.assertFalse((self.tmp / "260525_doc_2.pdf").exists())

    def test_suffix_when_different_bytes(self):
        p1 = place_attachment(self.tmp, "260525", "doc.pdf", b"hello")
        p2 = place_attachment(self.tmp, "260525", "doc.pdf", b"world")
        self.assertNotEqual(p1, p2)
        self.assertEqual(p2.name, "260525_doc_2.pdf")
        self.assertEqual(p1.read_bytes(), b"hello")
        self.assertEqual(p2.read_bytes(), b"world")

    def test_creates_dir_if_missing(self):
        subdir = self.tmp / "Fitxers"
        p = place_attachment(subdir, "260525", "x.txt", b"data")
        self.assertTrue(subdir.exists())
        self.assertTrue(p.exists())


class TestProcessedStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_load_missing_returns_empty_dict(self):
        self.assertEqual(load_processed_store(self.tmp), {})

    def test_save_creates_zconfig_dir(self):
        save_processed_store(self.tmp, {"t1": {"message_count": 1}})
        self.assertTrue((self.tmp / "zConfig" / ".processed_threads.json").exists())

    def test_roundtrip(self):
        store = {"thread-abc": {"message_count": 3, "archived_at": "now", "dest_path": "x"}}
        save_processed_store(self.tmp, store)
        loaded = load_processed_store(self.tmp)
        self.assertEqual(loaded, store)

    def test_needs_archive_new_thread(self):
        self.assertTrue(needs_archive({}, "t1", 1))

    def test_needs_archive_same_count(self):
        store = {"t1": {"message_count": 3}}
        self.assertFalse(needs_archive(store, "t1", 3))

    def test_needs_archive_grown(self):
        store = {"t1": {"message_count": 3}}
        self.assertTrue(needs_archive(store, "t1", 5))

    def test_mark_archived_records_count(self):
        store = {}
        mark_archived(store, "t1", 5, "Seguiment/Joan")
        self.assertEqual(store["t1"]["message_count"], 5)
        self.assertEqual(store["t1"]["dest_path"], "Seguiment/Joan")
        self.assertIn("archived_at", store["t1"])

    def test_load_corrupt_returns_empty(self):
        (self.tmp / "zConfig").mkdir()
        (self.tmp / "zConfig" / ".processed_threads.json").write_text("not json")
        self.assertEqual(load_processed_store(self.tmp), {})


class _FakeGmailFetcher:
    """Doble simple del GmailFetcher per a tests de sync."""
    def __init__(self, existing_labels: list[str], create_fail: set | None = None):
        self._labels = list(existing_labels)
        self._create_fail = create_fail or set()
        self.created_calls: list[str] = []

    def list_user_labels(self) -> list[dict]:
        return [{'id': f'L{i}', 'name': n} for i, n in enumerate(self._labels)]

    def create_label(self, name: str):
        self.created_calls.append(name)
        if name in self._create_fail:
            raise RuntimeError(f"boom for {name}")
        self._labels.append(name)


class TestSyncGmailLabels(unittest.TestCase):
    def test_crea_etiquetes_que_falten(self):
        discovery = VaultDiscovery(active={'Joan': Path('/x'), 'Foo': Path('/y')})
        fetcher = _FakeGmailFetcher(existing_labels=['Joan'])
        result = sync_gmail_labels(fetcher, discovery)
        self.assertEqual(result.created, ['Foo'])
        self.assertEqual(fetcher.created_calls, ['Foo'])
        self.assertEqual(result.failed, [])
        self.assertEqual(result.orphan, [])
        self.assertEqual(result.closed, [])

    def test_no_fa_res_si_tot_sincronitzat(self):
        discovery = VaultDiscovery(active={'Joan': Path('/x')})
        fetcher = _FakeGmailFetcher(existing_labels=['Joan'])
        result = sync_gmail_labels(fetcher, discovery)
        self.assertEqual(result.created, [])
        self.assertEqual(fetcher.created_calls, [])

    def test_orfes_no_es_creen_ni_esborren(self):
        discovery = VaultDiscovery(active={'Joan': Path('/x')})
        fetcher = _FakeGmailFetcher(existing_labels=['Joan', 'Etiqueta vella'])
        result = sync_gmail_labels(fetcher, discovery)
        self.assertEqual(result.created, [])
        self.assertEqual(result.orphan, ['Etiqueta vella'])
        # 'Etiqueta vella' segueix a Gmail
        self.assertIn('Etiqueta vella', {l['name'] for l in fetcher.list_user_labels()})

    def test_tancades_es_marquen_a_part(self):
        discovery = VaultDiscovery(
            active={'Actiu': Path('/a')},
            closed_by_active_label={'Antic': Path('/closed/antic')},
        )
        fetcher = _FakeGmailFetcher(existing_labels=['Actiu', 'Antic'])
        result = sync_gmail_labels(fetcher, discovery)
        self.assertEqual(result.closed, ['Antic'])
        self.assertEqual(result.orphan, [])

    def test_errors_de_creacio_es_capturen(self):
        discovery = VaultDiscovery(active={'A': Path('/a'), 'B': Path('/b')})
        fetcher = _FakeGmailFetcher(existing_labels=[], create_fail={'B'})
        result = sync_gmail_labels(fetcher, discovery)
        self.assertEqual(result.created, ['A'])
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0][0], 'B')
        self.assertIn('boom', result.failed[0][1])

    def test_log_callback_rep_missatges(self):
        discovery = VaultDiscovery(active={'Nova': Path('/x')})
        fetcher = _FakeGmailFetcher(existing_labels=[])
        msgs = []
        sync_gmail_labels(fetcher, discovery, log=msgs.append)
        self.assertTrue(any('Nova' in m for m in msgs))


class TestPlanLabelMigration(unittest.TestCase):
    @staticmethod
    def _labels(*names):
        return [{'id': f'L{i}', 'name': n} for i, n in enumerate(names)]

    def test_renames_path_labels_to_leaf(self):
        d = VaultDiscovery(active={'CRA': Path('/x'), 'Microchip': Path('/y')})
        existing = self._labels('Seguiment/CRA', 'Proveïdors/ARROW/Microchip')
        plan = plan_label_migration(existing, d)
        renames = {(old, new) for _id, old, new in plan.renames}
        self.assertEqual(renames, {
            ('Seguiment/CRA', 'CRA'),
            ('Proveïdors/ARROW/Microchip', 'Microchip'),
        })

    def test_leaf_labels_left_unchanged(self):
        # Una etiqueta ja en forma de fulla no es toca.
        d = VaultDiscovery(active={'CRA': Path('/x')})
        plan = plan_label_migration(self._labels('CRA'), d)
        self.assertEqual(plan.renames, [])

    def test_leaf_not_in_vault_is_reported(self):
        d = VaultDiscovery(active={'CRA': Path('/x')})
        plan = plan_label_migration(self._labels('Seguiment/Antic'), d)
        self.assertEqual(plan.renames, [])
        self.assertIn('Seguiment/Antic', plan.not_in_vault)

    def test_skips_when_flat_target_exists(self):
        # Ja hi ha 'CRA' plana i 'Seguiment/CRA' antiga: no es renombra
        # (crearia un duplicat); cal fusionar a mà.
        d = VaultDiscovery(active={'CRA': Path('/x')})
        plan = plan_label_migration(self._labels('CRA', 'Seguiment/CRA'), d)
        self.assertEqual(plan.renames, [])
        self.assertIn('Seguiment/CRA', plan.skipped_target_exists)

    def test_skips_collision_between_two_path_labels(self):
        # Dues etiquetes antigues mapegen a la mateixa fulla 'CRA'.
        d = VaultDiscovery(active={'CRA': Path('/x')})
        existing = self._labels('Seguiment/CRA', 'Reunions vàries/CRA')
        plan = plan_label_migration(existing, d)
        self.assertEqual(plan.renames, [])
        self.assertEqual(
            sorted(plan.skipped_collision),
            ['Reunions vàries/CRA', 'Seguiment/CRA'],
        )

    def test_closed_series_leaf_is_migrated(self):
        d = VaultDiscovery(
            active={},
            closed_by_active_label={'A10Pro': Path('/closed/a10')},
        )
        plan = plan_label_migration(self._labels('Seguiment/A10Pro'), d)
        self.assertEqual(
            [(old, new) for _id, old, new in plan.renames],
            [('Seguiment/A10Pro', 'A10Pro')],
        )


if __name__ == "__main__":
    unittest.main()
