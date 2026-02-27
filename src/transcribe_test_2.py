#!/usr/bin/env python3
"""
Prova de transcripció en català amb faster-whisper + model BSC
Configuració: local, MP3, amb initial_prompt de vocabulari d'empresa
"""

import time
import sys
import argparse
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURACIÓ — Edita aquesta secció
# ─────────────────────────────────────────────

# Model BSC recomanat: punctuated (genera puntuació i majúscules)
# Alternatives:
#   "BSC-LT/faster-whisper-large-v3-ca-punctuated-3370h"  ← recomanat
#   "BSC-LT/faster-whisper-bsc-large-v3-cat"              ← millor cobertura dialectal
#   "projecte-aina/whisper-large-v3-ca-3catparla"         ← millor WER en dades TV
MODEL_ID = "BSC-LT/faster-whisper-large-v3-ca-punctuated-3370h"

# Dispositiu: "cuda" si tens GPU NVIDIA, "cpu" en cas contrari
# compute_type: "float16" per a GPU, "int8" per a CPU (més ràpid i menys memòria)
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

# Vocabulari inicial de JCM Technologies
# Limit: ~224 tokens (~150-170 paraules). S'han prioritzat termes menys freqüents
# que Whisper té més probabilitat de transcriure malament.
INITIAL_PROMPT = """Reunió de seguiment de JCM Technologies, empresa de R+D.
Persones: Arxé, Autet, Balart, Baulenas, Beringues, Bohdan, Busquets, Capdevila,
Christophe, Dimitar, Farràs, Fumanya, Georgi, Griera, Hristov, Kleingries,
Matavera, Molist, Puigdesens, Renalias, Serrabassa, Solanich, Trullà, Vilaregut,
Yevheniia, Zipca.
Productes: HONOA, HONOACALL, HONOADOOR, HONOAMONITOR, EBASEDOOR, EBASEDOOR3,
EVOPROX, BIPROX, BTGO, CloudAssistant, DOORCAM, DOORDOC, NEXT-EBI, NEXT-EVO,
KAIMAI, Eurotrack, Radioband, Radiosens, ROLLER868, RSENS3, GOMINI, GO-PRO.
Termes: anti-passback, Desfire, Mifare, Wiegand, Vigik, Keyplus4, Polyswitch,
Watchdog, feature flags, panelat, plurifamiliar, RS485, NFC, TAG, VCP, MVS,
QCI, QATESTLAB, IDNEO, Prokodis, Marantech."""

# ─────────────────────────────────────────────
# PROGRAMA
# ─────────────────────────────────────────────

def check_dependencies():
    """Comprova que faster-whisper està instal·lat."""
    try:
        import faster_whisper
        return True
    except ImportError:
        print("ERROR: faster-whisper no està instal·lat.")
        print("Instal·la'l amb: pip install faster-whisper")
        return False


def transcribe(audio_path: str, use_prompt: bool = True) -> dict:
    """
    Transcriu un fitxer MP3 amb el model BSC.
    
    Args:
        audio_path: Ruta al fitxer MP3
        use_prompt: Si True, aplica l'initial_prompt configurat
    
    Returns:
        Dict amb 'text', 'segments', 'duration', 'elapsed', 'language'
    """
    from faster_whisper import WhisperModel

    print(f"\n{'='*60}")
    print(f"Model:    {MODEL_ID}")
    print(f"Dispositiu: {DEVICE} ({COMPUTE_TYPE})")
    print(f"Fitxer:   {audio_path}")
    print(f"Prompt:   {'Sí' if use_prompt else 'No'}")
    print(f"{'='*60}\n")

    # Càrrega del model
    print("⏳ Carregant model (primera vegada pot trigar uns minuts)...")
    t0 = time.time()
    model = WhisperModel(MODEL_ID, device=DEVICE, compute_type=COMPUTE_TYPE)
    t_load = time.time() - t0
    print(f"✅ Model carregat en {t_load:.1f}s\n")

    # Transcripció
    print("🎙️  Transcrivint...")
    t1 = time.time()

    prompt = INITIAL_PROMPT if use_prompt else None
    segments_gen, info = model.transcribe(
        audio_path,
        language="ca",
        beam_size=5,
        initial_prompt=prompt,
        word_timestamps=False,
    )

    # Iterar segments (generador)
    segments = []
    full_text_parts = []
    for seg in segments_gen:
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
        })
        full_text_parts.append(seg.text.strip())

    t_transcribe = time.time() - t1
    full_text = " ".join(full_text_parts)
    audio_duration = info.duration

    return {
        "text": full_text,
        "segments": segments,
        "duration": audio_duration,
        "elapsed": t_transcribe,
        "language": info.language,
        "language_prob": info.language_probability,
    }


def print_results(result: dict, label: str = "Resultat"):
    """Imprimeix els resultats de manera llegible."""
    print(f"\n{'─'*60}")
    print(f"📋 {label}")
    print(f"{'─'*60}")
    print(f"Idioma detectat:  {result['language']} (confiança: {result['language_prob']:.1%})")
    print(f"Durada àudio:     {result['duration']:.1f}s ({result['duration']/60:.1f} min)")
    print(f"Temps transcripció: {result['elapsed']:.1f}s")
    print(f"Factor velocitat: {result['duration']/result['elapsed']:.1f}x temps real")
    print(f"\n🗒️  TRANSCRIPCIÓ COMPLETA:\n")
    print(result["text"])
    print(f"\n📌 Segments ({len(result['segments'])} total):")
    for seg in result["segments"][:5]:  # Mostra els 5 primers
        print(f"  [{seg['start']:6.1f}s → {seg['end']:6.1f}s]  {seg['text']}")
    if len(result["segments"]) > 5:
        print(f"  ... i {len(result['segments']) - 5} segments més")


def save_transcript(result: dict, output_path: str):
    """Guarda la transcripció en un fitxer de text."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result["text"])
    print(f"\n💾 Transcripció guardada a: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Prova de transcripció en català amb faster-whisper + BSC"
    )
    parser.add_argument(
        "audio",
        help="Ruta al fitxer MP3 a transcriure"
    )
    parser.add_argument(
        "--sense-prompt",
        action="store_true",
        help="Desactiva l'initial_prompt (útil per comparar)"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Fitxer on guardar la transcripció (opcional)"
    )
    args = parser.parse_args()

    # Comprovacions prèvies
    if not check_dependencies():
        sys.exit(1)

    if not Path(args.audio).exists():
        print(f"ERROR: No es troba el fitxer: {args.audio}")
        sys.exit(1)

    # Transcripció
    use_prompt = not args.sense_prompt
    result = transcribe(args.audio, use_prompt=use_prompt)

    label = "Transcripció AMB initial_prompt" if use_prompt else "Transcripció SENSE initial_prompt"
    print_results(result, label=label)

    # Guardar si s'ha especificat
    if args.output:
        save_transcript(result, args.output)
    else:
        # Per defecte, guarda al costat de l'àudio
        output_default = Path(args.audio).stem + "_transcripcio.txt"
        save_transcript(result, output_default)


if __name__ == "__main__":
    main()
