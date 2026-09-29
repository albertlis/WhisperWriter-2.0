"""Wspólne źródło podziału train/validation/test. Używane przez eval_wer.py i train_lora.py."""

from pathlib import Path

from datasets import Audio, DatasetDict, load_dataset

DATA_DIR = Path(__file__).resolve().parent.parent / "training_data"
SAMPLE_RATE = 16000

# ponytail: bez odcięcia czasowego — bierzemy wszystko, co leży na dysku.
# UWAGA na konsekwencję: aplikacja dopisuje nagrania przy każdym użyciu, więc N rośnie,
# a przy zmiennym N train_test_split tasuje inaczej i ta sama próbka wędruje między
# treningiem a testem. Baseline i model porównywać WYŁĄCZNIE zmierzone tym samym
# przebiegiem, bez dyktowania w międzyczasie. Liczba próbek jest wypisywana niżej —
# jeśli różni się między dwoma pomiarami, porównanie jest nieważne.


def load_splits(
    test_size: float = 0.15, val_size: float = 0.12, seed: int = 0
) -> DatasetDict:
    """Ładuje training_data/ jako HF audiofolder i dzieli deterministycznie.

    metadata.jsonl ma już układ audiofolder (file_name + text), więc żadna
    konwersja nie jest potrzebna. Pole `text` to poprawka człowieka; `text_asr`
    (surowy output modelu) jedzie obok i służy tylko do wyciągania terminów.

    Trzy splity, nie dwa. `validation` istnieje wyłącznie po to, by
    `load_best_model_at_end` miało na czym wybierać checkpoint. Gdyby wybierało
    na `test`, raportowany potem WER byłby liczony na zbiorze, który brał udział
    w selekcji modelu — czyli zaniżony, i to tym bardziej, im więcej checkpointów
    porównamy. Klasyczny wyciek przez wybór, nie przez trening.
    """
    ds = load_dataset("audiofolder", data_dir=str(DATA_DIR), split="train")
    ds = ds.cast_column("audio", Audio(sampling_rate=SAMPLE_RATE))
    # audiofolder wciąga też pliki bez wpisu w metadata.jsonl (text = None) —
    # nagrania porzucone przed zatwierdzeniem w oknie review. Do treningu nie nadają się.
    before = len(ds)
    ds = ds.filter(
        lambda r: r["text"] is not None
        and r["text"].strip() != ""
        and r.get("ts") is not None
    )
    print(f"[data] {len(ds)} próbek (odrzucono {before - len(ds)})")
    # Sortowanie przed podziałem: kolejność z audiofolder zależy od systemu plików.
    # `file_name` znika — audiofolder zamienia je na kolumnę `audio`; `ts` jest unikalne.
    ds = ds.sort("ts")
    outer = ds.train_test_split(test_size=test_size, seed=seed)
    inner = outer["train"].train_test_split(test_size=val_size, seed=seed)
    splits = DatasetDict(
        train=inner["train"], validation=inner["test"], test=outer["test"]
    )
    print(
        f"[data] train {len(splits['train'])} / val {len(splits['validation'])} "
        f"/ test {len(splits['test'])}"
    )
    return splits
