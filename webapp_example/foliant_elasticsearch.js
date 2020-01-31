function performSearch(textToSearch) {
    // Specify your Elasticsearch instance API URL here
    const searchUrl = 'http://localhost:9200/docs_itv/_search';

    // Specify your site URL without trailing slash here
    const baseUrl = 'http://localhost';

    // Edit this query if needed. In this simple script, single API request is used for searching, and 50 first search results are shown. You may use AJAX to load more results dynamically
    let query = {
        "query": {
            "multi_match": {
                "query": textToSearch,
                "type": "phrase_prefix",
                "fields": [ "title^3", "content" ]
            }
        },
        "highlight": {
            "fields": {
                "content": {}
            }
        },
        "size": 50
    };

    let searchRequest = new XMLHttpRequest();

    searchRequest.open('POST', searchUrl, true);
    searchRequest.setRequestHeader('Content-Type', 'application/json; charset=utf-8');

    searchRequest.onload = function() {
        let response = JSON.parse(searchRequest.responseText);

        document.getElementById('foliant_elasticsearch_total').innerHTML = '<p class="foliant_elasticsearch_success">Results: ' + response.hits.total.value + '</p>';

        let output = '';

        for(let i = 0; i < response.hits.hits.length; i++) {
            output += '<h2>' + response.hits.hits[i]._source.title + '</h2><p>Page URL: <a href="' + baseUrl + response.hits.hits[i]._source.url + '">' + baseUrl + response.hits.hits[i]._source.url + '</a></p><pre>';

            for(let j = 0; j < response.hits.hits[i].highlight.content.length; j++) {
                output += response.hits.hits[i].highlight.content[j] + '\n\n';
            }

            output += '</pre>';
        }

        document.getElementById('foliant_elasticsearch_results').innerHTML = output;
    };

    searchRequest.onerror = function() {
        document.getElementById('foliant_elasticsearch_total').innerHTML = '<p class="foliant_elasticsearch_error">Error</p>';
    };

    searchRequest.send(JSON.stringify(query));
}
