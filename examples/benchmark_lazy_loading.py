"""
懒加载 vs 预加载性能对比演示
"""
import os
import sys
import time
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openguard.core.skill_loader import load_dynamic_skills, get_skill_count, clear_skill_cache


def create_large_skills(test_dir: str, num_skills: int = 50):
    """创建大量技能文件用于测试"""
    skills_dir = os.path.join(test_dir, "office", "skills")
    os.makedirs(skills_dir, exist_ok=True)
    
    print(f"创建 {num_skills} 个测试技能...")
    
    for i in range(num_skills):
        skill_dir = os.path.join(skills_dir, f"skill_{i:03d}")
        os.makedirs(skill_dir, exist_ok=True)
        
        # 创建较大的技能文件（模拟真实场景）
        skill_content = f"""name: Skill Number {i}
description: 这是第 {i} 个测试技能，用于性能基准测试

## 功能描述

这是一个模拟真实技能的测试文件，包含了较长的文档内容。
这样可以更准确地测试懒加载机制的性能优势。

## 使用场景

1. 场景一：基本功能
   - 描述：这个技能用于测试基本的加载性能
   - 参数：无
   - 返回：测试结果

2. 场景二：高级功能
   - 描述：测试复杂的文档结构
   - 参数：config: dict, options: list
   - 返回：处理结果

## 详细说明

### 配置选项

- option1: 默认值说明
- option2: 另一个配置项
- option3: 第三个选项

### 注意事项

1. 这是一个测试技能
2. 不要在生产环境使用
3. 仅用于性能测试

## 示例

```python
# 示例代码
result = skill_{i}.execute(config='config')
```

## 相关资源

- 官方文档: https://example.com/docs
- GitHub: https://github.com/example/skill-{i}
- 问题反馈: issues@example.com

## 版本历史

- v1.0.0: 初始版本
- v1.1.0: 添加新功能
- v1.2.0: 性能优化

## 许可证

MIT License

## 作者

Test Author <test@example.com>

---

这是第 {i} 个技能文件的结尾。
"""
        
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_content)
    
    print(f"[OK] 创建完成")
    return skills_dir


def benchmark():
    """性能基准测试"""
    print("=" * 70)
    print("OpenGuard 懒加载性能基准测试")
    print("=" * 70)
    
    # 创建临时测试目录
    temp_dir = tempfile.mkdtemp(prefix="openguard_bench_")
    
    # 修改环境变量
    original_env = os.environ.get("OPENGUARD_WORKSPACE")
    os.environ["OPENGUARD_WORKSPACE"] = temp_dir
    
    try:
        # 测试不同规模的技能数量
        test_sizes = [10, 30, 50, 100]
        
        print("\n" + "=" * 70)
        print("性能测试结果")
        print("=" * 70)
        print(f"{'技能数量':<15} | {'扫描耗时(ms)':<15} | {'首次调用(ms)':<15} | {'二次调用(ms)':<15}")
        print("-" * 70)
        
        for num_skills in test_sizes:
            # 创建技能
            skills_dir = create_large_skills(temp_dir, num_skills=num_skills)
            
            # 重新加载配置
            import importlib
            import openguard.core.config as config_module
            import openguard.core.skill_loader as skill_loader_module
            importlib.reload(config_module)
            importlib.reload(skill_loader_module)
            
            # 清除缓存
            skill_loader_module.clear_skill_cache()
            
            # 测试 1: 扫描耗时
            start = time.perf_counter()
            tools = skill_loader_module.load_dynamic_skills()
            scan_time = (time.perf_counter() - start) * 1000
            
            # 测试 2: 首次调用
            if tools:
                start = time.perf_counter()
                result = tools[0].func(mode='help')
                first_call_time = (time.perf_counter() - start) * 1000
                
                # 测试 3: 二次调用（缓存）
                start = time.perf_counter()
                result = tools[0].func(mode='help')
                second_call_time = (time.perf_counter() - start) * 1000
            else:
                first_call_time = 0
                second_call_time = 0
            
            print(f"{num_skills:<15} | {scan_time:<15.3f} | {first_call_time:<15.3f} | {second_call_time:<15.3f}")
            
            # 清理技能目录，准备下一轮测试
            shutil.rmtree(os.path.join(temp_dir, "office"), ignore_errors=True)
        
        print("=" * 70)
        print("\n测量范围：扫描、首次 help 与再次 help；每次 help 都校验说明内容。")
        print("本脚本没有运行预加载基线、测量内存或真实 LLM token 成本，不能据此计算端到端提升百分比。")

    finally:
        # 恢复环境
        if original_env is not None:
            os.environ["OPENGUARD_WORKSPACE"] = original_env
        else:
            os.environ.pop("OPENGUARD_WORKSPACE", None)
        
        # 清理
        shutil.rmtree(temp_dir, ignore_errors=True)
        print("\n[OK] 测试完成，临时目录已清理")


if __name__ == "__main__":
    benchmark()
