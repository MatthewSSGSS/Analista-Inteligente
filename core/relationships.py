def detect_relationships(sheets):
    result={k:[] for k in sheets}
    names=list(sheets)
    for i,a in enumerate(names):
        dfa=sheets[a]["processed"]
        for b in names[i+1:]:
            dfb=sheets[b]["processed"]
            for ca in dfa.columns:
                if ca not in dfb.columns: continue
                sa=dfa[ca].dropna(); sb=dfb[ca].dropna()
                if len(sa)==0 or len(sb)==0: continue
                overlap=len(set(sa.astype(str)) & set(sb.astype(str)))
                ratio=overlap/max(min(sa.nunique(),sb.nunique()),1)
                if ratio>=.5:
                    rel={"to_sheet":b,"column":ca,"overlap":round(ratio,3)}
                    result[a].append(rel)
                    result[b].append({"to_sheet":a,"column":ca,"overlap":round(ratio,3)})
    return result
