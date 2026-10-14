"""Exact verified spelling corrections; do not rewrite source or sealed data."""
ALIASES = {'Justin Herbery':'Justin Herbert', 'Kurt Waner':'Kurt Warner', 'Bill Vinocich':'Bill Vinovich'}
FIELDS = ('away_qb_name','home_qb_name','away_coach','home_coach','referee')


def canonical_name(value):
    value = value.strip() if isinstance(value,str) else value
    return ALIASES.get(value,value)


def corrected_row(row):
    row = dict(row)
    for field in FIELDS:
        if field in row:
            row[field] = canonical_name(row[field])
    return row
