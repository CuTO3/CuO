from Core.clock import BEIJING,day_bounds
def render(day,start,end,events):
    complete=end==day_bounds(day)[1]
    head=f"众声录｜{day}\n{start.astimezone(BEIJING):%m-%d %H:%M}—{end.astimezone(BEIJING):%m-%d %H:%M}"
    return head+"\n\n"+"\n\n".join(e["title"]+"\n"+e["body"] for e in events)
