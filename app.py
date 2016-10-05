import requests
from BeautifulSoup import BeautifulSoup
import datetime
from urlparse import urljoin
import blist
import xml.etree.ElementTree as ET
import time
import csv
from requests.exceptions import ConnectionError
import re
import sys
import uuid
import datetime
import os


mypath = os.getcwd()

def create_input_csv(i_file):
  '''Return file object if cachefile exists, create and return new cachefile if it doesn't exist'''
  input_dir = mypath
  if input_dir not in i_file:
    i_file = input_dir + '/' + i_file
  if os.path.isdir(input_dir):
    if os.path.isfile(i_file):
        print 'input.csv already Exist'
    else:
        if not os.path.isdir(os.path.dirname(i_file)):
            os.makedirs(os.path.dirname(i_file))
        f = open(i_file, 'w')
    return i_file

ifile = create_input_csv('input.csv')

def check_if_empty():
    with open(ifile, 'r') as checkFile:
        data = checkFile.read()
        if len(data) == 0:
            return True
        return False

if check_if_empty():
    with open(create_input_csv('input.csv'), 'a') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Symbol'])
        writer.writerow(['ATEC'])
        writer.writerow(['AAPL'])
        writer.writerow(['SNAK'])

if getattr(sys, 'frozen', False):
    # if frozen, get embeded file
    cacert = os.path.join(os.path.dirname(sys.executable), 'cacert.pem')
else:
    # else just get the default file
    cacert = requests.certs.where()

class ValueNotInFilingDocument(Exception):
    '''Raised when unable to extract an accounting metric from a filing document.'''
    
class XBRLDocument(object):
    '''wrapper for XBRL documents, lazily downloads XBRL text.'''
    def __init__(self, xbrl_url, gets_xbrl):
        self._xbrl_url = xbrl_url
        self._xbrl_dict_ = None
        self._contexts = {}
        self._get_xbrl = gets_xbrl
        
    @property
    def _xbrl_dict(self):
        if not self._xbrl_dict_:
            doc_text = self._get_xbrl(self._xbrl_url)
            xml_dict = xmltodict.parse(doc_text)
            self._xbrl_dict_ = self.find_node(xml_dict, 'xbrl')
        return self._xbrl_dict_

    def contexts(self, context_type):
        contexts = self._contexts.get(context_type, {})
        if not contexts:
            context_nodes = self.find_node(xml_dict=self._xbrl_dict, key='context')
            for context in context_nodes:
                try:
                    period = self.find_node(xml_dict=context, key='period')
                    self.find_node(xml_dict=period, key=context_type.characteristic_key)
                except KeyError:
                    continue
                else:
                    contexts[context['@id']] = context_type.from_period(period)
            self._contexts[context_type] = contexts
        return contexts

    @classmethod
    def gets_XBRL_from_edgar(cls, xbrl_url):
        return cls(xbrl_url=xbrl_url, gets_xbrl=get)
    
    @classmethod
    def gets_XBRL_locally(cls, file_path):
        return cls(xbrl_url=file_path, 
                   gets_xbrl=lambda file_path : open(file_path).read())


class Filing(object):
    '''Wrap SEC filings, 10-Ks, 10-Qs.'''
    def __init__(self, filing_date, document, next_filing=None):
        self._document = document
        self.date = filing_date
        self.next_filing = next_filing

    @classmethod
    def from_xbrl_url(cls, filing_date, xbrl_url):
        '''constructor.'''
        document = XBRLDocument.gets_XBRL_from_edgar(xbrl_url=xbrl_url)
        return cls(filing_date=filing_date, document=document)
    
    def __repr__(self):
        return '{} - {}'.format(self.__class__, self.date)

def get_filings(symbol, filing_type):
    '''Get the last xbrl filed before date.
        Returns a Filing object, return None if there are no XBRL documents
        prior to the date.

        Step 1 Search for the ticker and filing type,
        generate the urls for the document pages that have interactive data/XBRL.
       Step 2 : Get the document pages, on each page find the url for the XBRL document.
        Return a blist sorted by filing date.
    '''

    filings = blist.sortedlist(key=_filing_sort_key_func)
    document_page_urls = _get_document_page_urls(symbol, filing_type)
    for url in document_page_urls:
        filing = _get_filing_from_document_page(url)
        filings.add(filing)
    for i in range(len(filings) - 1):
        filings[i].next_filing = filings[i + 1]
    return filings

SEARCH_URL = ('http://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&'
              'CIK={symbol}&type={filing_type}&dateb=&owner=exclude&count=100')
def _get_document_page_urls(symbol, filing_type):
    '''Get the edgar filing document pages for the CIK.
    
    '''
    search_url = SEARCH_URL.format(symbol=symbol, filing_type=filing_type)
    search_results_page = get_edgar_soup(url=search_url)
    xbrl_rows = [row for row in 
                 search_results_page.findAll('tr') if 
                 row.find(text=re.compile('Interactive Data'))]
    for xbrl_row in xbrl_rows:
        documents_page = xbrl_row.find('a', {'id' : 'documentsbutton'})['href']
        documents_url = 'http://sec.gov' + documents_page
        yield documents_url

def _get_filing_from_document_page(document_page_url):
    '''Find the XBRL link on a page like 
    http://www.sec.gov/Archives/edgar/data/320193/000119312513300670/0001193125-13-300670-index.htm
    http://www.sec.gov/Archives/edgar/data/1350653/000135065316000097/atec-20160630-index.htm
    '''
    filing_page = get_edgar_soup(url=document_page_url)
    period_of_report_elem = filing_page.find('div', text='Filing Date')
    filing_date = period_of_report_elem.findNext('div', {'class' : 'info'}).text
    filing_date = datetime.date(*map(int, filing_date.split('-')))
    type_tds = filing_page.findAll('td', text='EX-101.INS')
    for type_td in type_tds:
        try:
            xbrl_link = type_td.findPrevious('a', text=re.compile('\.xml$')).parent['href']
        except AttributeError:
            continue
        else:
            if not re.match(pattern='\d\.xml$', string=xbrl_link):
                # we don't want files of the form 'jcp-20120504_def.xml'
                continue
            else:
                break
    xbrl_url = urljoin('http://www.sec.gov', xbrl_link)
    filing = Filing.from_xbrl_url(filing_date=filing_date, xbrl_url=xbrl_url)
    return filing

def _filing_sort_key_func(filing_or_date):
    if isinstance(filing_or_date, Filing):
        return filing_or_date.date
    elif isinstance(filing_or_date, datetime.datetime):
        return filing_or_date.date()
    else:
        return filing_or_date
    
def get_edgar_soup(url):
    response = get(url)
    return BeautifulSoup(response)

def get(url):
    '''requests.get wrapped in a backoff retry.
    
    '''
    wait = 0
    while wait < 5:
        try:
            return requests.get(url, verify=cacert).text
        except ConnectionError:
            print 'ConnectionError, trying again in ', wait
            time.sleep(wait)
            wait += 1
    else:
        raise

filename = mypath + '/SECresults/results' + str(uuid.uuid4()) + '.csv'

def append_to_csv(data, filename):
    with open(filename, 'a') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(data)
    return True

def find_violations(symbols, file_type):
    violated_urls = []
    for symbol in symbols:
        print 'Now searching ' + symbol + ' ...'
        counter = 0
        for url in _get_document_page_urls(symbol, file_type):
            file = _get_filing_from_document_page(url)
            xml_url = file._document._xbrl_url
            date = file.date
            data = get(xml_url).lower()
            bad_words = ['Until the Company achieves sustained profitability', 'does not have sufficient capital to meet its needs', 'continues to seek loans or equity placements to cover such cash needs', 'there can be no assurance that any additional funds will be available to cover expenses as they may be incurred', 'unable to raise additional capital', 'may be required to take additional measures to conserve liquidity', 'Suspending the pursuit of its business plan', 'The Company may need additional financing', 'We will incur expenses in connection with our SEC filing requirements and we may not be able to meet such costs', 'could jeopardize our filing status with the SEC', "raise substantial doubt about the Company's ability to continue as a going concern", 'taking certain steps to provide the necessary capital to continue its operations', "Executed an exchange agreement", "these factors raise substantial doubt about our ability to continue as a going concern", "If we do not obtain required additional equity or debt funding, our cash resources will be depleted and we could be required to materially reduce or suspend operations", "raise substantial doubt about our ability to continue as a going concern", "Our management intends to attempt to secure additional required funding through", "If we do not have sufficient funds to continue operations", "determined that it was out of compliance with certain of its financial covenants", "was in default of its covenants", "out of compliance with its financial convenants", "out of compliance with the company's financial convenants", "Has incurred consistent losses", "Has limited liquid assets", "dependent upon outside financing to continue operations", "plans to raise funds via private placements of its common stock and/or the issuance of debt instruments", "There is no assurance that the Company will be able to obtain the necessary funds through continuing equity and debt financing", "suspend the declaration of any further distributions on its", "to defer its interest payment"]
            #print bad_words
            if any(badWord.lower() in data for badWord in bad_words):
                data = [date, symbol, url]
                if append_to_csv(data, filename):
                    print 'results.csv Successfully updated.'
                counter += 1
                violated_urls.append(url)
        print 'Found ' + str(counter) + ' filing violtions in ' + symbol
    print 'All violated SEC filings stated below please copy and paste ...'
    print violated_urls

def get_symbols_via_csv(filename):
    symbols = []
    with open(filename, 'rU') as csvfile:
        reader = csv.DictReader(csvfile, dialect=csv.excel_tab)
        for row in reader:
            symbols.append(row['Symbol'])
    return symbols
    #print symbols

#get_symbols_via_csv('companylist.csv')

pathToCsvUser = mypath + '/input.csv'
fileTypeUser = '10-Q'

find_violations(get_symbols_via_csv(pathToCsvUser), fileTypeUser)

