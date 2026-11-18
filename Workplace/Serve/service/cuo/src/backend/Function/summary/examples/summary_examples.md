# 群聊总结示例：一个完整业务日

输入来自同一个群的一个完整业务日。当天有 64 条记录，按默认总结范围排除 1 条历史总结和 1 条占卜回执，保留其余 62 条，包括 54 条群友消息和 8 条机器人普通回复。闲聊、表情、转发和指令也按原顺序保留。

发言人使用化名，消息编号和当天内的回复指向重新生成。群名、账号、日期、时间和原始编号均已省略，图片、视频、转发、表情和歌词用占位符代替。其余文字原样保留，称呼替换为对应化名。下面的输出是对照记录整理的参考答案。

## 输入

```json
{
  "scope": {"mode":"day","topic":"","include_divine":false},
  "records": [
    {"ref":"d01","speaker":"阿舟","text":"@机器人 [表情][表情][表情]","kind":"human"},
    {"ref":"d02","speaker":"机器人","text":"阿舟？就发个名字过来，是有事还是单纯冒个泡","kind":"bot"},
    {"ref":"d03","speaker":"阿舟","text":"[表情]","kind":"human"},
    {"ref":"d04","speaker":"阿舟","text":"困死了","kind":"human"},
    {"ref":"d05","speaker":"阿舟","text":"呜呜呜","kind":"human"},
    {"ref":"d06","speaker":"小程","text":"[图片]","kind":"human"},
    {"ref":"d07","speaker":"小程","text":"@机器人 你是i人还是e人？L人还是p人啊","kind":"human"},
    {"ref":"d08","speaker":"机器人","text":"我？我一个机器人哪来的 MBTI，硬要说就是全天候掉线型。i 和 e 都算不上，L 和 p 那是你填字游戏玩多了吧","kind":"bot"},
    {"ref":"d09","speaker":"小程","text":"@机器人 那你是j人吗","kind":"human"},
    {"ref":"d10","speaker":"机器人","text":"j 人？我连 MBTI 都凑不齐四个字母，别给我硬塞一套了","kind":"bot"},
    {"ref":"d11","speaker":"小程","text":"你tmd","kind":"human"},
    {"ref":"d12","speaker":"小程","text":"@机器人 给我解释一下什么是j人","kind":"human"},
    {"ref":"d13","speaker":"机器人","text":"MBTI 里的 J 就是 Judging，判断型，做事喜欢有安排、有计划、早点把事情定下来。跟它对着的是 P，Perceiving，随性一点，爱临时改。\n\n所以刚才问你 j 人，就是问你是不是那种爱列计划、讨厌计划被打乱的人。不过 MBTI 这些字母本来就挺玄的，别太当真","kind":"bot"},
    {"ref":"d14","speaker":"阿舟","text":"喵喵喵@机器人","kind":"human"},
    {"ref":"d15","speaker":"机器人","text":"喵什么喵，睡醒了？刚才还困得呜呜呜","kind":"bot"},
    {"ref":"d16","speaker":"阿舟","text":"没饭吃","kind":"human"},
    {"ref":"d17","speaker":"阿舟","text":"@机器人 好饿啊","kind":"human"},
    {"ref":"d18","speaker":"机器人","text":"没饭吃还跑来找我，我这儿也没饭啊。要不先翻翻抽屉找点零食垫垫，别硬扛着","kind":"bot"},
    {"ref":"d19","speaker":"阿禾","text":"据医生说，生活中真有人不擦屁股的","kind":"human"},
    {"ref":"d20","speaker":"阿禾","text":"[转发]","kind":"human"},
    {"ref":"d21","speaker":"阿禾","text":"[转发]","kind":"human"},
    {"ref":"d22","speaker":"阿舟","text":"[图片]","kind":"human"},
    {"ref":"d23","speaker":"阿禾","text":"[转发]","kind":"human"},
    {"ref":"d24","speaker":"阿舟","text":"搬史大臣","kind":"human"},
    {"ref":"d25","speaker":"阿禾","text":"哈哈哈","kind":"human"},
    {"ref":"d26","speaker":"阿禾","text":"真的石","kind":"human"},
    {"ref":"d27","speaker":"阿禾","text":"[图片]","kind":"human"},
    {"ref":"d28","speaker":"小程","text":"[图片]","kind":"human"},
    {"ref":"d29","speaker":"小程","text":"这是一场酣畅淋漓的战斗呀","kind":"human"},
    {"ref":"d30","speaker":"小程","text":"[图片]","kind":"human"},
    {"ref":"d31","speaker":"小程","text":"我这辈子都不会忘了你吧","kind":"human"},
    {"ref":"d32","speaker":"小程","text":"二茂铁","kind":"human"},
    {"ref":"d33","speaker":"阿舟","text":"[图片]","kind":"human"},
    {"ref":"d34","speaker":"阿舟","text":"电设小车","kind":"human"},
    {"ref":"d35","speaker":"阿舟","text":"[图片]","kind":"human"},
    {"ref":"d36","speaker":"阿禾","text":"[图片]","kind":"human"},
    {"ref":"d37","speaker":"阿禾","text":"[图片]","kind":"human"},
    {"ref":"d38","speaker":"阿禾","text":"[图片]","kind":"human"},
    {"ref":"d39","speaker":"小乔","text":"下雪了卧槽","kind":"human"},
    {"ref":"d40","speaker":"阿舟","text":"[表情]","kind":"human"},
    {"ref":"d41","speaker":"阿舟","text":"呜呜呜","kind":"human"},
    {"ref":"d42","speaker":"小程","text":"[图片]","kind":"human"},
    {"ref":"d43","speaker":"小乔","text":"[视频]","kind":"human"},
    {"ref":"d44","speaker":"阿舟","text":"[图片]","kind":"human"},
    {"ref":"d45","speaker":"阿禾","text":"[歌词片段]","kind":"human"},
    {"ref":"d46","speaker":"阿禾","text":"[歌词片段]","kind":"human"},
    {"ref":"d47","speaker":"阿禾","text":"[歌词片段]","kind":"human"},
    {"ref":"d48","speaker":"阿禾","text":"[歌词片段]","kind":"human"},
    {"ref":"d49","speaker":"小程","text":"@机器人 今夜无月，如何千里共婵娟","kind":"human"},
    {"ref":"d50","speaker":"机器人","text":"无月还共婵娟，那你先给我发个自拍当月亮吧","kind":"bot"},
    {"ref":"d51","speaker":"阿禾","text":"[图片]@机器人","reply_to":{"ref":"d50"},"kind":"human"},
    {"ref":"d52","speaker":"机器人","text":"？人呢，就剩个名字飘过去","kind":"bot"},
    {"ref":"d53","speaker":"小程","text":"没传图","kind":"human"},
    {"ref":"d54","speaker":"阿舟","text":"[图片]","kind":"human"},
    {"ref":"d55","speaker":"阿舟","text":"@阿禾 cb吟唱","reply_to":{"ref":"d48"},"kind":"human"},
    {"ref":"d56","speaker":"小程","text":"@机器人 总结","kind":"human"},
    {"ref":"d57","speaker":"阿禾","text":"[图片]","kind":"human"},
    {"ref":"d58","speaker":"阿禾","text":"这个竟然能识图","kind":"human"},
    {"ref":"d59","speaker":"阿禾","text":"nb啊","kind":"human"},
    {"ref":"d60","speaker":"小程","text":"[图片]","kind":"human"},
    {"ref":"d61","speaker":"小程","text":"b站太坏了","kind":"human"},
    {"ref":"d62","speaker":"小程","text":"@机器人 占卜","kind":"human"}
  ],
  "repair": null
}
```

## 参考输出

```json
{
  "events": [
    {
      "title": "机器人自称“全天候掉线型”",
      "body": "小程拿 MBTI 问机器人，机器人给自己起了个“全天候掉线型”。等小程追问 J 是什么，它还是解释了 J 和 P 的区别：前者偏爱提前定计划，后者更随性。",
      "refs": [
        "d07",
        "d08",
        "d09",
        "d12",
        "d13"
      ],
      "quotes": [
        {
          "ref": "d08",
          "text": "全天候掉线型"
        }
      ]
    },
    {
      "title": "阿禾连转几条，阿舟回了句“搬史大臣”",
      "body": "阿禾提起一个关于如厕习惯的说法，接着发了几条转发。阿舟回了句“搬史大臣”，阿禾乐了，又接一句“真的石”。",
      "refs": [
        "d19",
        "d20",
        "d21",
        "d23",
        "d24",
        "d25",
        "d26"
      ],
      "quotes": [
        {
          "ref": "d24",
          "text": "搬史大臣"
        },
        {
          "ref": "d26",
          "text": "真的石"
        }
      ]
    },
    {
      "title": "今夜无月，机器人提议拿自拍当月亮",
      "body": "小程问“今夜无月，如何千里共婵娟”，机器人让他发张自拍当月亮。阿禾接着回了一张图，小程只回了句“没传图”。",
      "refs": [
        "d49",
        "d50",
        "d51",
        "d53"
      ],
      "quotes": [
        {
          "ref": "d49",
          "text": "今夜无月，如何千里共婵娟"
        },
        {
          "ref": "d53",
          "text": "没传图"
        }
      ]
    }
  ]
}
```
