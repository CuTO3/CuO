'''
本文件用途：Function/summary/son_function/merge_message.py 的后端实现。

配置字段：
未检测到直接读取共享 Settings 或环境变量；局部参数与间接依赖仍需逐项核查。
'''

from Core.clock import BEIJING,day_bounds
def render(day,start,end,events):
    complete=end==day_bounds(day)[1]
    head=f"众声录｜{day}\n{start.astimezone(BEIJING):%m-%d %H:%M}—{end.astimezone(BEIJING):%m-%d %H:%M}"
    return head+"\n\n"+"\n\n".join(e["title"]+"\n"+e["body"] for e in events)
