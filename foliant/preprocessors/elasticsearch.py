'''
Preprocessor for Foliant documentation authoring tool.

Calls Elasticsearch API to generate an index based on Markdown content.
'''

import re
import json
from pathlib import Path
from urllib import request
from urllib.error import HTTPError
from markdown import markdown
from bs4 import BeautifulSoup

from foliant.utils import output
from foliant.preprocessors.base import BasePreprocessor


class Preprocessor(BasePreprocessor):
    defaults = {
        'es_url': 'http://127.0.0.1:9200/',
        'index_name': '',
        'index_properties': {},
        'actions': ['create'],
        'use_chapters': True,
        'url_transform': [
            {'^(\S+)(\/index)?\.md$': '/\g<1>/'}
        ],
        'pandoc_path': 'pandoc',
        'targets': []
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.logger = self.logger.getChild('elasticsearch')

        self.logger.debug(f'Preprocessor inited: {self.__dict__}')

    def _get_page_url(self, markdown_file_path: str) -> str:
        url = str(markdown_file_path.relative_to(self.working_dir))
        url_transformation_rules = self.options['url_transform']

        if not isinstance(url_transformation_rules, list):
            url_transformation_rules = [url_transformation_rules]

        for url_transformation_rule in url_transformation_rules:
            for pattern, replacement in url_transformation_rule.items():
                url = re.sub(pattern, replacement, url)

        return url

    def _get_markdown_title(self, markdown_content: str) -> str or None:
        headings_found = re.search(
            r'^\#{1,6}\s+(.+?)(?:\s+\{\#\S+\})?\s*$',
            markdown_content,
            flags=re.MULTILINE
        )

        if headings_found:
            return headings_found.group(1)

        return None

    def _get_chapters_paths(self) -> list:
        def _recursive_process_chapters(chapters_subset):
            if isinstance(chapters_subset, dict):
                processed_chapters_subset = {}

                for key, value in chapters_subset.items():
                    processed_chapters_subset[key] = _recursive_process_chapters(value)

            elif isinstance(chapters_subset, list):
                processed_chapters_subset = []

                for item in chapters_subset:
                    processed_chapters_subset.append(_recursive_process_chapters(item))

            elif isinstance(chapters_subset, str):
                if chapters_subset.endswith('.md'):
                    chapters_paths.append(self.working_dir / chapters_subset)

                processed_chapters_subset = chapters_subset

            else:
                processed_chapters_subset = chapters_subset

            return processed_chapters_subset

        chapters_paths = []
        _recursive_process_chapters(self.config['chapters'])

        self.logger.debug(f'Chapters files paths: {chapters_paths}')

        return chapters_paths

    def _convert_markdown_to_plaintext(self, markdown_content: str) -> str:
        soup = BeautifulSoup(markdown(markdown_content), 'lxml')

        for non_text_node in soup(['style', 'script']):
            non_text_node.extract()

        return soup.get_text()

    def _create_index(self) -> None:
        if self.options['index_properties']:
            request_url = f'{self.options["es_url"].rstrip("/")}/{self.options["index_name"]}'

            self.logger.debug(
                'Calling Elasticsearch API to create an index with specified properties, ' +
                f'URL: {request_url}'
            )

            try:
                with request.urlopen(
                    request.Request(
                        request_url,
                        method='PUT',
                        headers={
                            'Content-Type': 'application/json; charset=utf-8'
                        },
                        data=json.dumps(self.options['index_properties'], ensure_ascii=False).encode('utf-8')
                    )
                ) as response:
                    response_status = response.getcode()
                    response_headers = response.info()
                    response_body = json.loads(response.read().decode('utf-8'))

            except HTTPError as not_ok:
                response_status = not_ok.getcode()
                response_headers = not_ok.info()
                response_body = json.loads(not_ok.read().decode('utf-8'))

            self.logger.debug(f'Response received, status: {response_status}')
            self.logger.debug(f'Response headers: {response_headers}')
            self.logger.debug(f'Response body, status: {response_body}')

            if response_status == 200 and response_body.get('acknowledged', None) is True:
                self.logger.debug('Index created')

            elif response_status == 400 and response_body.get(
                'error', {}
            ).get(
                'type', ''
            ) == 'resource_already_exists_exception':
                self.logger.debug('Index already exists')

            else:
                error_message = 'Failed to create an index'
                self.logger.error(f'{error_message}')
                raise RuntimeError(f'{error_message}')

        else:
            self.logger.debug('An index without specific properties will be created')

        if self.options['use_chapters']:
            self.logger.debug('Only files mentioned in chapters will be indexed')

            markdown_files_paths = self._get_chapters_paths()

        else:
            self.logger.debug('All files of the project will be indexed')

            markdown_files_paths = self.working_dir.rglob('*.md')

        data_for_indexing = ''

        for markdown_file_path in markdown_files_paths:
            self.logger.debug(f'Processing the file: {markdown_file_path}')

            with open(markdown_file_path, encoding='utf8') as markdown_file:
                markdown_content = markdown_file.read()

            if markdown_content:
                page_url = self._get_page_url(markdown_file_path)
                markdown_title = self._get_markdown_title(markdown_content)

                self.logger.debug(f'Adding the page, URL: {page_url}, title: {markdown_title}')

                data_for_indexing += '{"index": {}}\n' + json.dumps(
                    {
                        'url': page_url,
                        'title': markdown_title,
                        'text': self._convert_markdown_to_plaintext(markdown_content)
                    },
                    ensure_ascii=False
                ) + '\n'

            else:
                self.logger.debug('It seems that the file has no content')

        self.logger.debug(f'Data for indexing: {data_for_indexing}')

        request_url = f'{self.options["es_url"].rstrip("/")}/{self.options["index_name"]}/_bulk?refresh'

        self.logger.debug(f'Calling Elasticsearch API to add the content to the index, URL: {request_url}')

        with request.urlopen(
            request.Request(
                request_url,
                method='POST',
                headers={
                    'Content-Type': 'application/json; charset=utf-8'
                },
                data=data_for_indexing.encode('utf-8')
            )
        ) as response:
            response_status = response.getcode()
            response_headers = response.info()
            response_body = json.loads(response.read().decode('utf-8'))

        self.logger.debug(f'Response received, status: {response_status}')
        self.logger.debug(f'Response headers: {response_headers}')
        self.logger.debug(f'Response body, status: {response_body}')

        if response_status != 200 or response_body.get('errors', True):
            error_message = 'Failed to add content to the index'
            self.logger.error(f'{error_message}')
            raise RuntimeError(f'{error_message}')

        return None

    def _delete_index(self) -> None:
        request_url = f'{self.options["es_url"].rstrip("/")}/{self.options["index_name"]}/'

        self.logger.debug(f'Calling Elasticsearch API to delete the index, URL: {request_url}')

        try:
            with request.urlopen(
                request.Request(
                    request_url,
                    method='DELETE',
                )
            ) as response:
                response_status = response.getcode()
                response_headers = response.info()
                response_body = json.loads(response.read().decode('utf-8'))

        except HTTPError as not_ok:
            response_status = not_ok.getcode()
            response_headers = not_ok.info()
            response_body = json.loads(not_ok.read().decode('utf-8'))

        self.logger.debug(f'Response received, status: {response_status}')
        self.logger.debug(f'Response headers: {response_headers}')
        self.logger.debug(f'Response body, status: {response_body}')

        if response_status == 200 and response_body.get('acknowledged', None) is True:
            self.logger.debug('Index deleted')

        elif response_status == 404 and response_body.get(
            'error', {}
        ).get(
            'type', ''
        ) == 'index_not_found_exception':
            self.logger.debug('Index does not exist')

        else:
            error_message = 'Failed to delete the index'
            self.logger.error(f'{error_message}')
            raise RuntimeError(f'{error_message}')

        return None

    def apply(self):
        self.logger.info('Applying preprocessor')

        self.logger.debug(
            f'Allowed targets: {self.options["targets"]}, ' +
            f'current target: {self.context["target"]}'
        )

        if not self.options['targets'] or self.context['target'] in self.options['targets']:
            actions = self.options['actions']

            if not isinstance(self.options['actions'], list):
                actions = [actions]

            for action in actions:
                self.logger.debug(f'Applying action: {action}')

                if action == 'create':
                    self._create_index()

                elif action == 'delete':
                    self._delete_index()

                else:
                    self.logger.debug('Unknown action, skipping')

        self.logger.info('Preprocessor applied')
