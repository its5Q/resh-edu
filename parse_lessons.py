# God, please forgive me for the sins I've commited while coding this
import requests
from scrapy.selector import Selector
from trafilatura import extract
from parse import search
import io
import mammoth
import orjson
from multiprocessing.dummy import Pool
from threading import Lock
from bs4 import BeautifulSoup

def inner_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text().strip()

def full_traceback(func):
    import traceback, functools
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = "{}\n\nOriginal {}".format(e, traceback.format_exc())
            print(msg)
    return wrapper

@full_traceback
def process_lesson(lesson_id):
    print('Lesson ID:', lesson_id)
    result = {'id': lesson_id}

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36'
    }
    sess = requests.Session()

    resp = sess.get(f'https://resh.edu.ru/subject/lesson/{lesson_id}/', headers=headers)
    if resp.status_code != 200:
        print(f'Error getting lesson #{lesson_id}', resp.status_code)
        return

    sel = Selector(text=resp.text)

    if '/conspectus/' in resp.text:
        # Old lesson format

        print('Old lesson format')
        # Parsing basic lesson info
        result['format'] = 'old'
        result['subject'] = sel.xpath('//h1[@class="content-title"]/a/text()').get('')
        # result['lesson_num'] = sel.xpath('//div[@class="lesson-video-slide"]/p/text()').get('')
        result['title'] = sel.css('.lesson-content').xpath('./h2/text()').get('')
        result['author'] = sel.xpath('//a[@class="lesson-video__teacher"]/text()').get('')
        result['grade'] = int(sel.xpath('//h1[@class="content-title"]/a/@href').get('/subject/0/0/').split('/')[3])

        # Requesting lesson summary
        summary_resp = sess.post(f'https://resh.edu.ru/subject/lesson/{lesson_id}/conspectus/', data={'ajax': 'true'}, headers=headers | {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})
        result['summary'] = Selector(text=summary_resp.text).css('.lesson-video__conspectus').get('')

        # Requesting a list of excercises 
        # excercises_resp = sess.post(f'https://resh.edu.ru/lesson/{lesson_id}/exercise/', data={'ajax': 'true'}, headers=headers | {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})
        # excercise_urls = ['https://resh.edu.ru' + path for path in Selector(text=excercises_resp.text).xpath('//a/@href').getall()]
        result['excercises'] = []

        # Parsing excercises
        excercise_resp = sess.get(f'https://resh.edu.ru/subject/lesson/{lesson_id}/training/', headers=headers)
        excercises = Selector(text=excercise_resp.text).css('.js-test-item')

        # POST our test "answers" so we can retrieve the correct answers from server
        sess.post(f'https://resh.edu.ru/subject/lesson/{lesson_id}/train/result/', data={"answers": {"1": {"2": 3}}}, headers=headers | {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})
    else:
        # New lesson format

        print('New lesson format')
        # Parsing basic lesson info
        result['format'] = 'new'
        result['subject'] = sel.xpath('//ul[@class="breadcrumbs"]/li[3]/a/text()').get('')
        result['title'] = sel.css('.lesson-title__item').xpath('.//h1/text()').get('')
        result['author'] = '' # who the hell knows who the author is for new lessons
        try:
            result['grade'] = search("{:d} класс", sel.xpath('//title').get())[0]
        except Exception:
            result['grade'] = 0

        # Requesting lesson summary
        if 'conspect/' in resp.text:
            summary_resp = sess.get(f'https://resh.edu.ru/subject/lesson/{lesson_id}/conspect/', headers=headers)
            result['summary'] = Selector(text=summary_resp.text).css('.test-words').get('')
        else:
            summary_path = sel.css('.main-header__content-nav-list').xpath('./a[2]/@href').get()
            if summary_path.endswith('.docx'):
                docx_file = io.BytesIO(requests.get(f'https://resh.edu.ru{summary_path}', headers=headers).content)
                try:
                    result['summary'] = mammoth.convert_to_html(docx_file).value
                except Exception:
                    # unlucky
                    result['summary'] = ''

        result['excercises'] = []

        # Parsing excercises
        excercise_resp = sess.get(f'https://resh.edu.ru/subject/lesson/{lesson_id}/train/', headers=headers)
        excercises = Selector(text=excercise_resp.text).css('.scene')

        # POST our dummy test "answers" so we can retrieve the correct answers from server
        sess.post(f'https://resh.edu.ru/subject/lesson/{lesson_id}/train/result/', data={"answers": {"1": {"2": 3}}}, headers=headers | {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})


    for excercise in excercises:
        e_result = {}
        e_result['id'] = int(excercise.xpath('.//@data-test-id').get('0'))
        if e_result['id'] == '0':
            print('No excercies id found, skipping')
            continue
        
        if result['format'] == 'old':
            e_result['title'] = excercise.xpath('.//h1[@class="content-title"]/text()').get('').strip()
        else:
            e_result['title'] = excercise.xpath('.//div[@class="scene__title"]/h5/text()').get('').strip()
        e_result['question'] = excercise.css('.test__title').get('')
        e_result['question_type'] = excercise.xpath('.//*/@data-interaction-type').get('')
        interaction_id = excercise.xpath('.//*/@data-interaction-identifier').get('')
        
        answer_resp = sess.get(f'https://resh.edu.ru/tests/{e_result["id"]}/get-answers', headers=headers | {'X-Requested-With': 'XMLHttpRequest'}).json()

        # The pain begins...
        if e_result['question_type'] == 'single_choice' or e_result['question_type'] == 'multiple_choice':
            correct_answers = [ans['value'] for ans in answer_resp[interaction_id]]
            e_result['choices'] = []
            
            if e_result['question_type'] == 'single_choice':
                for choice in excercise.css('.interaction-item').xpath('.//table/tr'):
                    choice_id = choice.xpath('.//input[@type="radio"]/@value').get()
                    choice_html = choice.xpath('.//td[2]').get()

                    e_result['choices'].append({
                        'id': choice_id,
                        'html': choice_html,
                        'correct': choice_id in correct_answers
                    })
            else:
                for choice_id, choice_html in zip(excercise.css('.interaction-item').xpath('.//input/@value').getall(), excercise.css('.interaction-item').xpath('.//label').getall()):
                        e_result['choices'].append({
                        'id': choice_id,
                        'html': choice_html,
                        'correct': choice_id in correct_answers
                    })
        elif e_result['question_type'] == 'text_entry':
            #print(e_result)
            e_result['text'] = excercise.css('.test-words').get('')
            e_result['answers'] = []
            for blank_id in excercise.css('.test-words').xpath('.//input[@class="interaction-item"]/@data-interaction-identifier').getall():
                e_result['answers'].append(answer_resp[blank_id][0]['value'])
        elif e_result['question_type'] == 'gap_match_text':
            correct_answers = {ans['value'].split()[0]: ans['value'].split()[1] for ans in answer_resp[interaction_id]}
            e_result['text'] = excercise.css('.text-with-gaps').get('')
            e_result['choices'] = list(map(lambda s: s.strip(), excercise.css('.interaction-choices').xpath('.//div/text()').getall()))
            e_result['answers'] = []

            for gap in excercise.css('.interaction-gap'):
                gap_id = gap.xpath('.//@data-id').get()
                e_result['answers'].append(
                    excercise.css('.interaction-choices').xpath(f'.//div[@data-id="{correct_answers[gap_id]}"]/text()').get().strip()
                )
        elif e_result['question_type'] == 'gap_match_color':
            e_result['text'] = excercise.css('.test-sentence__text-area').get('')
            e_result['answers'] = {ans['value'].split()[0]: ans['value'].split()[1] for ans in answer_resp[interaction_id]}
        elif e_result['question_type'] == 'two_sets_association':
            # Parsing all nodes and their html
            choices = {}
            for choice in excercise.css('.left-column').xpath('.//div[@data-id]'):
                choices[choice.xpath('./@data-id').get()] = choice.css('.item-lace').get()

            for choice in excercise.css('.right-column').xpath('.//div[@data-id]'):
                choices[choice.xpath('./@data-id').get()] = choice.css('.item-lace').get()

            try:
                e_result['pairs'] = [(choices[ans['value'].split()[0]], choices[ans['value'].split()[1]]) for ans in answer_resp[interaction_id]]
                e_result['choices'] = list(choices.values())
            except Exception as ex:
                print(f'Error parsing association pairs (lesson {result["id"]}, test {e_result["id"]})')
        elif e_result['question_type'] == 'inline_choice':
            correct_answers = {key: answer_resp[key][0]['value'] for key in answer_resp}
            e_result['choices'] = []
            e_result['answers'] = []
            for selection in excercise.xpath('.//select[@class="interaction-item"]'):
                selection_id = selection.xpath('./@data-interaction-identifier').get()
                answers = list(map(lambda s: s.strip(), selection.xpath('.//option/text()').getall()))
                answer = selection.xpath(f'.//option[@data-id="{correct_answers[selection_id]}"]/text()').get('').strip()

                if not answer or not answers:
                    continue

                e_result['choices'].append(answers)
                e_result['answers'].append(answer)
        elif e_result['question_type'] == 'order':
            correct_answers = {key: [ans['value'] for ans in answer_resp[key]] for key in answer_resp}
            e_result['choices'] = []
            e_result['answers'] = []
            for scramble in excercise.css('.interaction-item'):
                answer_id = scramble.xpath('./@data-interaction-identifier').get()
                scrambled = list(map(lambda s: inner_text(s), scramble.xpath('.//span').getall()))
                answer = []
                
                for correct_choice in correct_answers[answer_id]:
                    answer.append(
                        inner_text(scramble.xpath(f'.//span[@data-interaction-choice-identifier="{correct_choice}"]').get())
                    )

                if not scrambled or not answer:
                    continue

                e_result['choices'].append(scrambled)
                e_result['answers'].append(answer)
        elif e_result['question_type'] == 'gap_match_table':
            correct_answers = {ans['value'].split()[1]: ans['value'].split()[0] for ans in answer_resp[interaction_id]}
            titles = dict(zip(excercise.xpath('.//table/tbody/tr/td/@data-identifier').getall(), excercise.xpath('.//table/thead/tr/th/h4/text()').getall()))
            e_result['columns'] = excercise.xpath('.//table/thead/tr/th/h4/text()').getall()
            e_result['answers'] = [[] for _ in e_result['columns']]

            for choice in excercise.css('.interaction-choice'):
                choice_id = choice.xpath('./@data-id').get()
                e_result['answers'][e_result['columns'].index(titles[correct_answers[choice_id]])].append(choice.get())
        else: # If I'm going to add another type of interaction support, I'll go insane, this is enough.
            print(f'[Q:{e_result["id"]}] Unsupported interaction type: {e_result["question_type"]}')
            continue

        result['excercises'].append(e_result)

    with write_lock:
        ofile.write(orjson.dumps(result, option=orjson.OPT_APPEND_NEWLINE))

write_lock = Lock()
ofile = open('./data/raw.jsonl', 'wb')

with Pool(8) as pool:
    pool.map(process_lesson, range(1, 10000))
    pool.close()
    pool.join()
# You know what, the Pain Remains triology really fits the mood for writing web scrapers