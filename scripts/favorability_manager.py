"""
好感度管理脚本 - 用于查看和修改用户好感度
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.common.database.database_model import Favorability, PersonInfo


def get_favorability_level(fav: int) -> str:
    """根据好感度获取等级"""
    if fav >= 90:
        return "挚友"
    elif fav >= 70:
        return "好友"
    elif fav >= 50:
        return "熟人"
    elif fav >= 30:
        return "认识"
    elif fav >= 10:
        return "陌生"
    else:
        return "厌恶"


def get_person_name(person_id: str) -> str:
    """获取用户名称"""
    try:
        person = PersonInfo.get_or_none(PersonInfo.person_id == person_id)
        if person:
            return person.nickname or person.person_name or person_id[:8]
    except:
        pass
    return person_id[:8]


def list_all():
    """列出所有好感度记录"""
    records = Favorability.select().order_by(Favorability.favorability.desc())
    if not records:
        print("\n📭 暂无好感度记录")
        return
    
    print("\n" + "=" * 70)
    print(f"{'序号':<4} {'用户名':<20} {'好感度':<10} {'等级':<8} {'互动次数':<10}")
    print("=" * 70)
    
    for i, record in enumerate(records, 1):
        name = get_person_name(record.person_id)
        print(f"{i:<4} {name:<20} {record.favorability:<10} {record.level:<8} {record.total_interactions:<10}")
    
    print("=" * 70)
    print(f"共 {len(records)} 条记录")


def search_user(keyword: str):
    """搜索用户"""
    # 先搜索 PersonInfo 表
    persons = PersonInfo.select().where(
        (PersonInfo.person_name.contains(keyword)) |
        (PersonInfo.nickname.contains(keyword)) |
        (PersonInfo.person_id.contains(keyword))
    )
    
    results = []
    for person in persons:
        fav_record = Favorability.get_or_none(Favorability.person_id == person.person_id)
        results.append({
            "person_id": person.person_id,
            "name": person.nickname or person.person_name or person.person_id[:8],
            "favorability": fav_record.favorability if fav_record else 50,
            "level": fav_record.level if fav_record else "熟人",
            "total_interactions": fav_record.total_interactions if fav_record else 0
        })
    
    if not results:
        print(f"\n❌ 未找到包含 '{keyword}' 的用户")
        return None
    
    print("\n" + "=" * 70)
    print(f"{'序号':<4} {'用户名':<20} {'好感度':<10} {'等级':<8} {'person_id':<30}")
    print("=" * 70)
    
    for i, r in enumerate(results, 1):
        print(f"{i:<4} {r['name']:<20} {r['favorability']:<10} {r['level']:<8} {r['person_id'][:28]:<30}")
    
    print("=" * 70)
    return results

    
def modify_favorability(person_id: str, new_value: int):
    """修改好感度"""
    new_value = max(0, min(150, new_value))  # 限制在 0-100
    new_level = get_favorability_level(new_value)
    
    record = Favorability.get_or_none(Favorability.person_id == person_id)
    if record:
        old_value = record.favorability
        record.favorability = new_value
        record.level = new_level
        record.save()
        print(f"\n✅ 好感度已修改: {old_value} → {new_value} ({new_level})")
    else:
        # 创建新记录
        import time
        Favorability.create(
            person_id=person_id,
            favorability=new_value,
            level=new_level,
            total_interactions=0,
            positive_interactions=0,
            negative_interactions=0,
            last_interaction=time.time(),
            created_at=time.time()
        )
        print(f"\n✅ 已创建新记录，好感度: {new_value} ({new_level})")


def interactive_modify():
    """交互式修改"""
    keyword = input("\n请输入要搜索的用户名或ID: ").strip()
    if not keyword:
        return
    
    results = search_user(keyword)
    if not results:
        return
    
    if len(results) == 1:
        choice = 1
    else:
        try:
            choice = int(input("\n请输入要修改的用户序号 (0 取消): "))
            if choice == 0:
                return
            if choice < 1 or choice > len(results):
                print("❌ 无效的序号")
                return
        except ValueError:
            print("❌ 请输入有效的数字")
            return
    
    selected = results[choice - 1]
    print(f"\n已选择: {selected['name']} (当前好感度: {selected['favorability']})")
    
    try:
        new_value = int(input("请输入新的好感度 (0-100): "))
        modify_favorability(selected["person_id"], new_value)
    except ValueError:
        print("❌ 请输入有效的数字")


def main():
    print("\n" + "=" * 40)
    print("      💕 好感度管理工具 💕")
    print("=" * 40)
    
    while True:
        print("\n操作菜单:")
        print("  1. 查看所有好感度记录")
        print("  2. 搜索用户")
        print("  3. 修改好感度")
        print("  4. 直接输入 person_id 修改")
        print("  0. 退出")
        
        choice = input("\n请选择操作 (0-4): ").strip()
        
        if choice == "0":
            print("\n👋 再见!")
            break
        elif choice == "1":
            list_all()
        elif choice == "2":
            keyword = input("请输入搜索关键词: ").strip()
            if keyword:
                search_user(keyword)
        elif choice == "3":
            interactive_modify()
        elif choice == "4":
            person_id = input("请输入 person_id: ").strip()
            if person_id:
                try:
                    new_value = int(input("请输入新的好感度 (0-100): "))
                    modify_favorability(person_id, new_value)
                except ValueError:
                    print("❌ 请输入有效的数字")
        else:
            print("❌ 无效的选择")


if __name__ == "__main__":
    main()
