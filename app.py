#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BD数据模型名称规范化工具
"""
import os
import re
import json
from flask import Flask, render_template, request, jsonify
import pandas as pd

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

CSV_PATH = r'C:\Users\hkhu3\Downloads\配置推送文件\BD数据源\BD数据效果明细.csv'
MODELS_JSON = r'C:\Users\hkhu3\bd_data_tool\models.json'

# 标准格式: 产品_BD_dk-产品-ruleXXX-P-前筛-T-日期-F-得分_机型
# 其中 P-前筛、T-日期、F-得分、_机型 均为可选

DEVICE_SUFFIX = r'(?:_(APPLE|HUAWEI|XIAOMI|OPPO|VIVO|HONOR|IP-[A-Z]+|RICH-[A-Z]+|CARD-[A-Z]+))?$'

def load_known_models():
    """从配置文件加载已知模型主体列表"""
    try:
        with open(MODELS_JSON, 'r', encoding='utf-8') as f:
            models = json.load(f)
            return sorted(models, key=len, reverse=True)
    except:
        return []

def save_known_models(models):
    """保存模型主体列表到配置文件"""
    with open(MODELS_JSON, 'w', encoding='utf-8') as f:
        json.dump(sorted(models), f, ensure_ascii=False, indent=4)

class ModelNameNormalizer:

    # 已知模型主体集合（从配置文件加载）
    KNOWN_MODELS = load_known_models()

    def match_model(self, body):
        """从body中识别模型主体，返回 (model_key, rest)"""
        for km in self.KNOWN_MODELS:
            if body == km or body.startswith(km + '-') or body.startswith(km + '_'):
                rest = body[len(km):]
                if rest.startswith('-'):
                    rest = rest[1:]
                return km, rest
        # 未知：取 dk-xxx-ruleXXX 部分作为 unknown 标识
        return 'unknown', body

    def parse(self, name):
        """
        解析模型名称，返回各段内容和问题列表。
        不重构名称，只做识别和问题标注。
        """
        parts = {
            'product': '',       # 产品前缀，如 HFQ
            'data_source': '',   # 数据源，如 BD
            'model_body': '',    # dk-xxx 完整主体
            'model_key': '',     # 已知模型主体，如 dk-HB-ruleA20260225
            'model_rest': '',    # 模型主体之后的内容
            'p_filter': '',      # P- 后的前筛内容
            't_date': '',        # T- 后的日期
            'f_score': '',       # F- 后的得分/TAG内容
            'device': '',        # 末尾机型
        }
        issues = []

        # 1. 提取末尾机型 _XXXX
        device_match = re.search(r'_((?:IP|RICH|CARD)-[A-Z]+|APPLE|HUAWEI|XIAOMI|OPPO|VIVO|HONOR)$', name)
        if device_match:
            parts['device'] = device_match.group(1)
            core = name[:device_match.start()]
        else:
            core = name

        # 2. 提取 产品_数据源_ 前缀
        prefix_match = re.match(r'^([A-Z0-9]+)_([A-Z]+)_(dk-.+)$', core)
        if prefix_match:
            parts['product'] = prefix_match.group(1)
            parts['data_source'] = prefix_match.group(2)
            body = prefix_match.group(3)
        else:
            # 尝试只有产品_
            prefix_match2 = re.match(r'^([A-Z0-9]+)_(dk-.+)$', core)
            if prefix_match2:
                parts['product'] = prefix_match2.group(1)
                parts['data_source'] = ''
                body = prefix_match2.group(2)
                issues.append('缺少数据源(BD)')
            else:
                issues.append('前缀格式异常')
                parts['model_body'] = core
                return parts, issues

        parts['model_body'] = body

        # 2b. R9: 规范化小写 -p- 为 -P-
        body = re.sub(r'-p-', '-P-', body)
        parts['model_body'] = body

        # 2c. 精确识别模型主体
        model_key, rest_after_model = self.match_model(body)
        parts['model_key'] = model_key   # 如 dk-HB-ruleA20260225 或 unknown
        parts['model_rest'] = rest_after_model  # 模型主体之后的内容（含P/T/F）

        # 3. 检查数据源是否为 BD
        if parts['data_source'] and parts['data_source'] != 'BD':
            issues.append(f'数据源应为BD，当前为{parts["data_source"]}')

        # 4. 提取 T-日期：支持多T段、T-日期-日期格式，R4/R8规则
        # R4: 检测重复T段如 -T-d1-T-d2 或 -T-d1-T-d1-d2，合并为 d1-d2
        # R8: 检测同日期范围如 d1-d1，折叠为单日期 d1
        t_segments = re.findall(r'-T-(\d{6,8}(?:-\d{6,8})?)', body)
        if t_segments:
            # 如果有多个T段，合并为范围
            if len(t_segments) > 1:
                dates = []
                for seg in t_segments:
                    if '-' in seg:
                        dates.extend(seg.split('-'))
                    else:
                        dates.append(seg)
                # 标准化日期格式
                dates = [d if len(d) == 8 else ('20' + d if d[:2] not in ('20', '19') else d) for d in dates]
                # R8: 去重相同日期
                if len(dates) >= 2 and dates[0] == dates[-1]:
                    parts['t_date'] = dates[0]
                else:
                    parts['t_date'] = f"{dates[0]}-{dates[-1]}"
            else:
                # 单个T段
                seg = t_segments[0]
                if '-' in seg:
                    d1, d2 = seg.split('-')
                    d1 = d1 if len(d1) == 8 else ('20' + d1 if d1[:2] not in ('20', '19') else d1)
                    d2 = d2 if len(d2) == 8 else ('20' + d2 if d2[:2] not in ('20', '19') else d2)
                    # R8: 去重相同日期
                    parts['t_date'] = d1 if d1 == d2 else f"{d1}-{d2}"
                else:
                    raw = seg
                    parts['t_date'] = raw if len(raw) == 8 else ('20' + raw if raw[:2] not in ('20', '19') else raw)

        # 4b. 无显式T-日期时，从 model_rest 尾部提取日期（如 dk-xxx-20260312 格式）
        if not parts['t_date']:
            mr = parts.get('model_rest', '')
            if mr:
                # model_rest 是纯日期或纯日期范围（如 20260312 或 20260119-20260312）
                mr_match = re.match(r'^(\d{6,8})(?:-(\d{6,8}))?$', mr)
                if mr_match:
                    raw = mr_match.group(2) if mr_match.group(2) else mr_match.group(1)
                    parts['t_date'] = raw if len(raw) == 8 else (raw if raw[:2] in ('20', '19') else '20' + raw)

        # 4c. 提取 TAG 作为 F-得分（TAG-X-Y → f_score=X-Y）
        tag_match = re.search(r'-TAG-([A-Z0-9](?:-[A-Z0-9])*)', body)
        if tag_match:
            parts['f_score'] = tag_match.group(1)

        # 5. 提取 P-前筛（R6: -P-\d{8} 视为日期误标，作为停止条件）
        p_match = re.search(r'-P-(.+?)(?=-P-\d{8}|-T-\d{6,8}|-F-|-TAG-|-\d{6,8}-\d{6,8}$|-\d{6,8}$|$)', body)
        if p_match:
            parts['p_filter'] = p_match.group(1)

        # 6. 提取 F-得分（-F- 显式段，优先级低于TAG）
        if not parts['f_score']:
            f_match = re.search(r'-F-([^_]+)', body)
            if f_match:
                parts['f_score'] = f_match.group(1)

        # 7. 检查命名规范问题
        # 检查是否有 dk- 开头
        if not body.startswith('dk-'):
            issues.append('模型名应以dk-开头')

        # 检查T-日期是否存在
        if not parts['t_date']:
            # 有些老模型用日期范围如 20260119-20260303，不算问题
            date_range = re.search(r'-(\d{8})-(\d{8})$', body)
            if not date_range:
                issues.append('缺少T-日期')

        # 检查产品前缀与模型名中的产品是否一致
        # 如 HFQ_BD_dk-XHF-... 产品前缀HFQ但模型用XHF，这是正常的（交叉投放）
        # 不做强制检查，只做提示

        # 8. 尝试生成规范化名称（仅修正可自动修正的问题）
        normalized = name  # 默认不变

        # 如果缺少数据源，补充BD
        if not parts['data_source'] and parts['product']:
            normalized = f"{parts['product']}_BD_{body}"
            if parts['device']:
                normalized += f"_{parts['device']}"

        return parts, issues

    def normalize(self, name):
        """
        极简版规范化：
        1. 识别模型主体（KNOWN_MODELS）
        2. 提取得分F - 只要出现 -A-、-B-、-C-、-D-、-E- 就提取为得分
        """
        parts, issues = self.parse(name)

        if '前缀格式异常' in issues:
            return name, parts, issues

        product = parts['product']
        data_source = parts['data_source'] or 'BD'
        device = parts['device']
        device_suffix = f'_{device}' if device else ''
        model_key = parts.get('model_key', 'unknown')

        # 规则：识别得分F - 在整个模型名称中查找 -A-、-B-、-C-、-D-、-E-
        f_score = ''
        # 查找所有 -字母- 模式，只保留 ABCDE
        score_matches = re.findall(r'-([ABCDE])(?:-|_|$)', name)
        if score_matches:
            # 去重并按字母顺序排列
            f_score = '-'.join(sorted(set(score_matches)))

        if not f_score:
            f_score = 'ALL'

        # 更新 parts
        parts['f_score'] = f_score

        # 重建规范化名称：产品_BD_模型主体-F-得分
        normalized = f"{product}_{data_source}_{model_key}-F-{f_score}{device_suffix}"

        return normalized, parts, issues


RULES_XLSX = r'C:\Users\hkhu3\Downloads\配置推送文件\BD数据源\模型名修正映射关系_20260323.xlsx'


@app.route('/api/learn_rules')
def learn_rules():
    """返回极简规则列表"""
    rules = [
        {
            'id': 'R1',
            'title': '模型主体识别',
            'count': len(ModelNameNormalizer.KNOWN_MODELS),
            'description': '从KNOWN_MODELS字典中精确匹配已知模型主体，保持不变',
            'pattern_before': '任意模型名称',
            'pattern_after': '识别并保留已知模型主体（如 dk-HB-ruleA20260225）',
            'examples': [
                {'before': 'HB_BD_dk-HB-ruleA20260225-P-HB-RTA16-20-A-260225', 'after': '模型主体: dk-HB-ruleA20260225'},
                {'before': 'HFQ_BD_dk-XHF-ruleA20260114-B-20260312', 'after': '模型主体: dk-XHF-ruleA20260114'},
                {'before': 'YXH_BD_dk-YXH-ruleA20260227-C-D-260227', 'after': '模型主体: dk-YXH-ruleA20260227'},
            ]
        },
        {
            'id': 'R2',
            'title': '得分字段识别（ABCDE）',
            'count': 0,
            'description': '在模型名称中查找 -A-、-B-、-C-、-D-、-E- 模式，提取为得分字段F。如果找到多个，去重并按字母顺序排列。没有找到则补充F-ALL',
            'pattern_before': '产品_BD_模型主体-...-A-... 或 产品_BD_模型主体-...-B-C-...',
            'pattern_after': '产品_BD_模型主体-F-A 或 产品_BD_模型主体-F-B-C',
            'examples': [
                {'before': 'HB_BD_dk-HB-ruleA20260225-P-HB-RTA16-20-A-260225-260302', 'after': 'HB_BD_dk-HB-ruleA20260225-F-A'},
                {'before': 'HFQ_BD_dk-HFQ-ruleA20260226-P-HFQ-MIX-B-C-260226', 'after': 'HFQ_BD_dk-HFQ-ruleA20260226-F-B-C'},
                {'before': 'YXH_BD_dk-YXH-ruleA-D-260115-E', 'after': 'YXH_BD_dk-YXH-ruleA-F-D-E'},
                {'before': 'HB_BD_dk-HB-ruleB20260225-P-HB-RTA16-20-260225', 'after': 'HB_BD_dk-HB-ruleB20260225-F-ALL（无ABCDE，补充ALL）'},
            ]
        },
    ]

    return jsonify({
        'success': True,
        'total': len(ModelNameNormalizer.KNOWN_MODELS),
        'rules': rules
    })

@app.route('/api/learn_rules_old')
def learn_rules_old():
    """旧版规则学习（保留备份）"""
    try:
        df = pd.read_excel(RULES_XLSX, header=None)
        df.columns = ['before', 'after']
        df = df.dropna(subset=['before'])
        df['before'] = df['before'].astype(str).str.strip()
        df['after'] = df['after'].astype(str).str.strip()

        total = len(df)
        changed = df[df['before'] != df['after']]

        rules = []

        def ex(rows, n=3):
            return [{'before': r['before'], 'after': r['after']}
                    for _, r in rows.head(n).iterrows()]

        # R1: 缺少F-得分 → F-ALL
        r1 = changed[
            ~changed['before'].str.contains(r'-F-', regex=False) &
            changed['after'].str.contains(r'-F-ALL', regex=False) &
            changed['before'].str.contains(r'-T-', regex=False)
        ]
        rules.append({'id': 'R1', 'count': len(r1), 'title': '缺少得分段 → 补充 F-ALL',
            'pattern': '...模型名-P-xxx-T-YYYYMMDD（无F段）',
            'fix': '...模型名-P-xxx-T-YYYYMMDD-F-ALL',
            'desc': '当模型名包含T-日期但没有F-得分段时，末尾补充 -F-ALL',
            'examples': ex(r1)})

        # R2: 缺少P-前筛 → P-ALL
        r2 = changed[
            ~changed['before'].str.contains(r'-P-', regex=False) &
            changed['after'].str.contains(r'-P-ALL', regex=False)
        ]
        rules.append({'id': 'R2', 'count': len(r2), 'title': '缺少前筛段 → 补充 P-ALL',
            'pattern': '...模型名-T-YYYYMMDD-F-xxx（无P段）',
            'fix': '...模型名-P-ALL-T-YYYYMMDD-F-xxx',
            'desc': '当模型名没有 -P- 前筛段时，在T前插入 -P-ALL',
            'examples': ex(r2)})

        # R3: TAG → F
        r3 = changed[
            changed['before'].str.contains(r'-TAG-', regex=False) &
            ~changed['after'].str.contains(r'-TAG-', regex=False)
        ]
        rules.append({'id': 'R3', 'count': len(r3), 'title': 'TAG 标记转换为 F 标记',
            'pattern': '...-T-YYYYMMDD-TAG-A',
            'fix': '...-T-YYYYMMDD-F-A',
            'desc': '-TAG-X-Y 与 -F-X-Y 含义相同，统一改写为 F 标记',
            'examples': ex(r3)})

        # R4: 重复T段合并
        r4 = changed[
            changed['before'].str.contains(r'-T-\d+-T-\d+', regex=True) &
            ~changed['after'].str.contains(r'-T-\d+-T-\d+', regex=True)
        ]
        rules.append({'id': 'R4', 'count': len(r4), 'title': '重复T段合并为日期区间',
            'pattern': '...-T-date1-T-date1-date2-TAG-X',
            'fix': '...-T-date1-date2-F-X',
            'desc': '连续两个T段，第二个T的起始日期与第一个相同时，合并为单个T日期区间',
            'examples': ex(r4)})

        # R5: P-filter内含裸日期（-P-xxx-YYYYMMDD-F-）→ 加T标记
        r5 = changed[
            changed['before'].str.contains(r'-P-[A-Za-z].*-\d{8}-F-', regex=True) &
            changed['after'].str.contains(r'-T-\d{8}-F-', regex=True) &
            ~changed['before'].str.contains(r'-T-', regex=False)
        ]
        rules.append({'id': 'R5', 'count': len(r5), 'title': 'P-filter 内含裸日期 → 识别为 T-日期',
            'pattern': '...-P-XHF-UNHIT-20260122-F-A（日期无T前缀）',
            'fix': '...-P-XHF-UNHIT-T-20260122-F-A',
            'desc': 'P-前筛内容后紧跟8位数字日期且无T前缀时，该日期是T-日期段，需补充T标记',
            'examples': ex(r5)})

        # R6: P误标为T位置标签（-P-YYYYMMDD-F-）
        r6 = changed[
            changed['before'].str.contains(r'-P-\d{8}-F-', regex=True) &
            changed['after'].str.contains(r'-T-\d{8}-F-', regex=True)
        ]
        rules.append({'id': 'R6', 'count': len(r6), 'title': 'P标签误用于日期位置 → 改为T标签',
            'pattern': '...-P-前筛-P-20260107-F-A-E（第二个P应为T）',
            'fix': '...-P-前筛-T-20260107-F-A-E',
            'desc': 'P-filter之后出现 -P-YYYYMMDD 形式时，该P是误写，应改为 -T-YYYYMMDD',
            'examples': ex(r6)})

        # R7: 6位日期补充20前缀
        r7 = changed[
            changed['before'].str.contains(r'-T-26\d{4}', regex=True) &
            changed['after'].str.contains(r'-T-2026\d{4}', regex=True)
        ]
        rules.append({'id': 'R7', 'count': len(r7), 'title': '6位日期（YYMMDD）补全为8位（YYYYMMDD）',
            'pattern': '...-T-260101-260131-...',
            'fix': '...-T-20260101-20260131-...',
            'desc': 'T段内6位日期若以26/25开头（YYMMDD格式），补充"20"前缀变为8位',
            'examples': ex(r7)})

        # R8: 相同日期范围去重 T-date-date → T-date
        r8 = changed[
            changed['before'].str.contains(r'-T-(\d{8})-\1', regex=True) &
            ~changed['after'].str.contains(r'-T-(\d{8})-\1', regex=True)
        ]
        rules.append({'id': 'R8', 'count': len(r8), 'title': '相同日期范围去重',
            'pattern': '...-T-20260120-20260120-...',
            'fix': '...-T-20260120-...',
            'desc': 'T段日期区间起止日期相同时，保留单个日期即可',
            'examples': ex(r8)})

        # R9: 小写p → 大写P
        r9 = changed[changed['before'].str.contains(r'-p-', regex=False)]
        rules.append({'id': 'R9', 'count': len(r9), 'title': '小写 -p- 改为大写 -P-',
            'pattern': '...-p-RTA-A-T-...',
            'fix': '...-P-RTA-A-T-...',
            'desc': '字段分隔标记均应大写，-p- 是笔误，统一改为 -P-',
            'examples': ex(r9)})

        # R10: 废弃老格式
        r10 = changed[changed['after'].isin(['废弃', 'nan', ''])]
        rules.append({'id': 'R10', 'count': len(r10), 'title': '废弃旧命名格式（无有效映射）',
            'pattern': 'BD_DK-HFQ-ruler1-xxx / BD_YQG-ruler2-xxx 等',
            'fix': '废弃（不参与规范化）',
            'desc': '使用大写DK、ruler1/ruler2、老产品名称前缀等2024年前的旧格式模型，无法映射到新规范，标记为废弃',
            'examples': ex(r10)})

        return jsonify({
            'success': True,
            'total': total,
            'changed': len(changed),
            'unchanged': total - len(changed),
            'rules': rules
        })
    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'trace': traceback.format_exc()})


normalizer = ModelNameNormalizer()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/rules')
def rules_page():
    return render_template('rules.html')


@app.route('/models')
def models_page():
    return render_template('models.html')


@app.route('/api/models', methods=['GET'])
def get_models():
    """获取所有模型主体"""
    return jsonify({
        'success': True,
        'models': sorted(ModelNameNormalizer.KNOWN_MODELS, key=len, reverse=True),
        'count': len(ModelNameNormalizer.KNOWN_MODELS)
    })


@app.route('/api/models', methods=['POST'])
def add_model():
    """添加新模型主体"""
    data = request.json
    model_name = data.get('name', '').strip()

    if not model_name:
        return jsonify({'success': False, 'error': '模型名称不能为空'}), 400

    if not model_name.startswith('dk-'):
        return jsonify({'success': False, 'error': '模型名称必须以 dk- 开头'}), 400

    if model_name in ModelNameNormalizer.KNOWN_MODELS:
        return jsonify({'success': False, 'error': '该模型已存在'}), 400

    # 添加到列表并保存
    ModelNameNormalizer.KNOWN_MODELS.append(model_name)
    ModelNameNormalizer.KNOWN_MODELS = sorted(ModelNameNormalizer.KNOWN_MODELS, key=len, reverse=True)
    save_known_models(ModelNameNormalizer.KNOWN_MODELS)

    return jsonify({'success': True, 'message': '添加成功', 'model': model_name})


@app.route('/api/models/<path:model_name>', methods=['DELETE'])
def delete_model(model_name):
    """删除模型主体"""
    if model_name not in ModelNameNormalizer.KNOWN_MODELS:
        return jsonify({'success': False, 'error': '模型不存在'}), 404

    # 从列表中移除并保存
    ModelNameNormalizer.KNOWN_MODELS.remove(model_name)
    save_known_models(ModelNameNormalizer.KNOWN_MODELS)

    return jsonify({'success': True, 'message': '删除成功'})


@app.route('/api/upload_file', methods=['POST'])
def upload_file():
    """处理用户上传的文件"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '未选择文件'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': '未选择文件'}), 400

        # 读取文件内容
        if file.filename.endswith('.csv'):
            # 尝试多种编码读取CSV文件
            encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'utf-8-sig']
            df = None
            last_error = None

            for encoding in encodings:
                try:
                    file.seek(0)  # 重置文件指针
                    df = pd.read_csv(file, encoding=encoding)
                    break  # 成功读取，跳出循环
                except (UnicodeDecodeError, UnicodeError) as e:
                    last_error = e
                    continue

            if df is None:
                return jsonify({'success': False, 'error': f'无法识别文件编码，请确保文件是有效的CSV文件。尝试的编码: {", ".join(encodings)}'}), 400

        elif file.filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file)
        else:
            return jsonify({'success': False, 'error': '不支持的文件格式，请选择 CSV 或 Excel 文件'}), 400

        return process_dataframe(df)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/load_data')
def load_data():
    try:
        df = pd.read_csv(CSV_PATH, encoding='gbk')
        return process_dataframe(df)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def process_dataframe(df):
    """处理数据框并返回 JSON"""
    try:
        # 列映射
        cols = df.columns.tolist()
        col_model_name = cols[0]      # 模型名称
        col_model_type = cols[1]      # 任务类型
        col_product = cols[3]         # 产品名称
        col_arrival = cols[5]         # 短信到达量
        col_click = cols[8]           # 点击
        col_register = cols[9]        # 注册量
        col_apply = cols[10]          # 申完量
        col_approve = cols[11]        # 过审量
        col_settlement = cols[12]     # 结算金额
        col_cost = cols[13]           # 成本
        col_profit = cols[14]         # 毛利
        col_roi = cols[22]            # ROI
        col_click_rate = cols[15]     # 点击率
        col_reg_rate = cols[17]       # 注册/点击
        col_apply_rate = cols[20]     # 申完/注册
        col_approve_rate = cols[21]   # 过审/申完

        results = []
        for idx, row in df.iterrows():
            original = str(row.iloc[0]).strip()
            normalized, parts, issues = normalizer.normalize(original)

            # 辅助函数：安全获取数值
            def safe_num(val):
                try:
                    return float(val) if pd.notna(val) else 0
                except:
                    return 0

            results.append({
                'id': idx,
                'original': original,
                'normalized': normalized,
                'is_changed': original != normalized,
                'issues': issues,
                'parts': parts,
                'product': str(row[col_product]),
                'model_type': str(row[col_model_type]),
                'arrival': safe_num(row[col_arrival]),
                'click': safe_num(row[col_click]),
                'register': safe_num(row[col_register]),
                'apply': safe_num(row[col_apply]),
                'approve': safe_num(row[col_approve]),
                'settlement': safe_num(row[col_settlement]),
                'cost': safe_num(row[col_cost]),
                'profit': safe_num(row[col_profit]),
                'roi': safe_num(row[col_roi]),
                'click_rate': safe_num(row[col_click_rate]),
                'reg_rate': safe_num(row[col_reg_rate]),
                'apply_rate': safe_num(row[col_apply_rate]),
                'approve_rate': safe_num(row[col_approve_rate]),
            })
        return jsonify({'success': True, 'total': len(results), 'data': results})
    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'trace': traceback.format_exc()})


@app.route('/api/save_feedback', methods=['POST'])
def save_feedback():
    try:
        data = request.json
        feedback_file = os.path.join(os.path.dirname(__file__), 'feedback.json')
        feedbacks = []
        if os.path.exists(feedback_file):
            with open(feedback_file, 'r', encoding='utf-8') as f:
                feedbacks = json.load(f)
        # 更新已有记录或追加
        existing = next((i for i, fb in enumerate(feedbacks) if fb.get('id') == data.get('id')), None)
        if existing is not None:
            feedbacks[existing] = data
        else:
            feedbacks.append(data)
        with open(feedback_file, 'w', encoding='utf-8') as f:
            json.dump(feedbacks, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    print('BD数据模型名称规范化工具')
    print('请访问: http://localhost:5000')
    app.run(debug=True, host='0.0.0.0', port=5000)
