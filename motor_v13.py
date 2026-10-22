"""RotaAds V1.3: motor explicável de seleção de publicidade.

Sem aprendizagem automática ou perfis de passageiros. Usa hora Europe/Lisbon,
zonas autorizadas da V1.2, prioridades manuais e contagens agregadas do ecrã.
A opção de otimização é OFF por defeito em todos os ecrãs migrados.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LISBON = ZoneInfo('Europe/Lisbon')
DIAS = ('Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom')


def portugal_now(utc=None):
    return (utc or datetime.now(timezone.utc)).astimezone(LISBON)


def parse_schedule(start='', end='', days=''):
    """Normaliza horários e dias. Rejeita dados parciais/inválidos."""
    start = (start or '').strip()
    end = (end or '').strip()
    if bool(start) != bool(end):
        raise ValueError('Preencha as duas horas ou deixe ambas vazias.')
    for value in (start, end):
        if value:
            try:
                parsed = datetime.strptime(value, '%H:%M')
                if parsed.strftime('%H:%M') != value:
                    raise ValueError
            except ValueError as error:
                raise ValueError('Utilize a hora no formato HH:MM (00:00 a 23:59).') from error
    if start and start == end:
        raise ValueError('A hora inicial deve ser diferente da final.')
    if isinstance(days, str):
        days = [x for x in days.split(',') if x != '']
    try:
        numbers = {int(day) for day in days}
    except (TypeError, ValueError) as error:
        raise ValueError('Dias da semana inválidos.') from error
    if any(x < 0 or x > 6 for x in numbers):
        raise ValueError('Dias da semana inválidos.')
    return start, end, ','.join(str(x) for x in sorted(numbers)) if start else ''


def schedule_allowed(c, when=None):
    """Sem horário definido, não altera comportamento V1.2.

    Para períodos noturnos (p.ex. 22:00-02:00), a madrugada de terça
    pertence ao período que começou na segunda-feira.
    """
    start, end = c['horario_inicio'] or '', c['horario_fim'] or ''
    if not start or not end:
        return True
    local = portugal_now(when)
    minutes = local.hour * 60 + local.minute
    a, b = (int(x[:2]) * 60 + int(x[3:]) for x in (start, end))
    days = {int(x) for x in (c['dias_semana'] or '').split(',') if x != ''}
    if a < b:
        return a <= minutes < b and (not days or local.weekday() in days)
    if minutes >= a:
        return not days or local.weekday() in days
    if minutes < b:
        return not days or (local.weekday() - 1) % 7 in days
    return False


def weighted_playlist(items, recent_counts=None, size=18):
    """Sequência balanceada para ecrãs com modo inteligente.

    Itens: {'id', 'peso', 'segmentada', 'anunciante_id'}. Sem dados pessoais.
    A frequência agregada das últimas três horas atenua sobreexposição.
    O algoritmo dá oportunidade às campanhas de menor prioridade.
    """
    if not items:
        return []
    if len(items) == 1:
        return items[:]
    recent_counts = recent_counts or {}
    weights = []
    for c in items:
        priority = max(1, min(5, int(c.get('peso', 3) or 3)))
        geo_factor = 1.4 if c.get('segmentada') else 1.0
        history = max(0, int(recent_counts.get(c['id'], 0)))
        weight = priority * geo_factor / (1 + history / 35.0)
        weights.append(max(0.15, weight))
    total = sum(weights)
    currents = [0.0] * len(items)
    sequence = []
    prior = None
    for _ in range(max(1, min(48, size))):
        for j in range(len(items)):
            currents[j] += weights[j]
        indexes = sorted(range(len(items)), key=lambda j: (currents[j], -j), reverse=True)
        chosen = indexes[0]
        # Evitar o mesmo criativo em reprodução consecutiva, quando possível.
        if prior is not None and items[chosen]['id'] == prior:
            for candidate in indexes[1:]:
                # Evitar repetições apenas quando a pontuação está próxima;
                # prioridades 5:1 devem realmente produzir frequências distintas.
                if (items[candidate]['id'] != prior
                        and currents[chosen] - currents[candidate] < total * 0.20):
                    chosen = candidate
                    break
        currents[chosen] -= total
        sequence.append(items[chosen])
        prior = items[chosen]['id']
    return sequence


def summarize_hours(timestamps):
    """Agrupa timestamps UTC por hora local portuguesa (sem localização pessoal)."""
    result = [0] * 24
    for value in timestamps:
        try:
            d = datetime.fromisoformat(value)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            result[d.astimezone(LISBON).hour] += 1
        except (ValueError, TypeError, OverflowError):
            continue
    return result
