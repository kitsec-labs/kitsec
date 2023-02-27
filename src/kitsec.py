import os
import time
import click
import socket
import platform
import requests
import paramiko
import warnings
import concurrent
import subprocess
import pandas as pd
from tqdm import tqdm
from bs4 import BeautifulSoup
from tabulate import tabulate
from urllib.parse import urlparse
from Wappalyzer import Wappalyzer, WebPage

#replace subfinder
#todo: add web fuzzing: https://github.com/ffuf/ffuf
#check: https://github.com/six2dez/reconftw


#ignore JAVA warnings on wappalyzer
warnings.filterwarnings("ignore", category=UserWarning, module='bs4')
warnings.filterwarnings("ignore", category=UserWarning, message=".*It looks like you're parsing an XML document using an HTML parser.*")
warnings.filterwarnings("ignore", message="""Caught 'unbalanced parenthesis at position 119' compiling regex""", category=UserWarning )


@click.group()
def cli():
    pass

@click.command()
def linode():
    host = click.prompt("Enter the IP address of the Linode server to connect to")
    username = click.prompt("Enter the limited user account to use for connecting to the Linode server")
    password = click.prompt("Enter the password for the user account", hide_input=True)

    command = "df"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=username, password=password)
    stdin, stdout, stderr = client.exec_command(command)
    print(stdout.read().decode())
    client.close()

def passive_enumerator(domain):
    """
    Uses Subfinder to enumerate subdomains for a given domain.

    Args:
        domain (str): The domain to enumerate subdomains for.

    Returns:
        set: A set of subdomains.
    """
    with open(os.devnull, 'w') as nullfile:
        subfinder_output = subprocess.check_output(['subfinder', '-d', domain], stderr=nullfile)

    subdomains = set(subfinder_output.decode('utf-8').strip().split('\n'))

    return subdomains

def active_enumerator(domain):
    """
    Enumerates subdomains for a given domain, and checks which ones are active.
    Args:
        domain (str): The domain to enumerate subdomains for.
    Returns:
        set or None: A set of subdomains, or None if no subdomains were found.
    """
    subdomains = set()
    dir_path = "../lists/active_enumerator"
    if not os.path.isdir(dir_path):
        raise FileNotFoundError(f"Subdomains directory '{dir_path}' not found")
    file_names = [file_name for file_name in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, file_name)) and file_name.endswith(".txt")]
    total_files = len(file_names)
    for i, file_name in enumerate(file_names):
        file_path = os.path.join(dir_path, file_name)
        with open(file_path, "r") as subdomain_file:
            for line in tqdm(subdomain_file, desc="Active enumeration", unit="Subdomains"):
                subdomain = line.strip()
                full_domain = subdomain + "." + domain
                try:
                    response = requests.head("https://" + full_domain, timeout=3)
                    if response.status_code < 400:
                        subdomains.add(subdomain)
                except:
                    pass
    if subdomains:
        return subdomains
    else:
        return set()

def fetch_tech(url):
    if not url.startswith('http'):
        url = 'https://' + url
    webpage = WebPage.new_from_url(url)
    wappalyzer = Wappalyzer.latest()
    technologies = []
    for tech in wappalyzer.analyze(webpage):
        technologies.append(tech)
    return technologies


@click.command()
@click.argument('domain')
@click.option('-r', '--request', is_flag=True, help='Test subdomains and print http response for active ones')
@click.option('-t', '--technology', is_flag=True, help='Analyze technology used by subdomains')
def enumerator(domain, request, technology):
    """
    Enumerates subdomains for a given domain using Subfinder and active enumeration.

    Args:
        domain (str): The domain to enumerate subdomains for.
        request (bool): Flag to indicate if subdomains should be tested and http response printed for active ones.
        technology (bool): Flag to indicate if technology used by subdomains should be analyzed.

    Returns:
        pandas.DataFrame: A DataFrame containing the enumerated subdomains.
    """
    # Get subdomains using Subfinder
    subdomains = passive_enumerator(domain)

    # Perform active enumeration and add to subdomains
#    active_subdomains = active_enumerator(domain)
#    subdomains.update(active_subdomains)

    if request:
        # Test subdomains and print http response for active ones
        response_table = []
        for subdomain in tqdm(subdomains, desc='Testing subdomains', unit='subdomain', leave=False):
            try:
                response = requests.get(f'http://{subdomain}')
                response_table.append([subdomain, response.status_code, response.reason])
            except requests.exceptions.RequestException:
                pass

        if technology:
            # Analyze technology used by subdomains
            tech_table = []
            for subdomain, status, reason in tqdm(response_table, desc='Analyzing technology', unit='subdomain', leave=False):
                tech = fetch_tech(subdomain)
                tech_table.append([subdomain, status, reason, tech])
            # sort tech_table by status in ascending order
            tech_table = sorted(tech_table, key=lambda x: -x[1])
            click.echo(tabulate(tech_table, headers=['Subdomain', 'Status', 'Reason', 'Technology']))
        else:
            # sort response_table by status in ascending order
            response_table = sorted(response_table, key=lambda x: x[1])
            click.echo(tabulate(response_table, headers=['Subdomain', 'Status', 'Reason']))

    elif technology:
        # Analyze technology used by subdomains
        technologies = []
        for subdomain in tqdm(subdomains, desc='Analyzing technology', unit='subdomain', leave=False):
            tech = fetch_tech(subdomain)
            technologies.append([subdomain, tech])
        click.echo(tabulate(technologies, headers=['Subdomain', 'Technology']))
        click.echo('Analyzing technology Done!')

    else:
        # Just print the subdomains
        subdomains_list = df['Subdomain'].tolist()
        with tqdm(total=len(subdomains_list), desc='Enumerating subdomains', unit='subdomain') as pbar:
            subdomains_list = [[subdomain] for subdomain in subdomains_list]
            click.echo(tabulate(subdomains_list, headers=['Subdomain']))
            pbar.update(len(subdomains_list))


@click.command()
@click.argument('url')
@click.option('--num-threats', '-t', default=6, help='Number of parallel threats to send requests from')
@click.option('--num-requests', '-r', default=200, help='Number of requests to send from each threat')
@click.option('--num-retries', '-n', default=4, help='Number of times to retry failed requests')
@click.option('--pause-before-retry', '-p', default=3000, help='Number of milliseconds to wait before retrying a failed request')
def intruder(url, num_threats, num_requests, num_retries, pause_before_retry):
    """
    Sends HTTP requests to a given URL with a specified number of threats and requests.

    Args:
        url (str): The URL to send the requests to (i.e. subdomain.domain.com).
        num_threats (int, optional): The number of parallel threats to send requests from. Defaults to 6.
        num_requests (int, optional): The number of requests to send from each threat. Defaults to 200.
        num_retries (int, optional): The number of times to retry failed requests. Defaults to 4.
        pause_before_retry (int, optional): The number of milliseconds to wait before retrying a failed request. 
            Defaults to 3000.
    """
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url
    prepared_request = requests.Request('GET', url).prepare()
    results = []
    with requests.Session() as session:
        adapter = requests.adapters.HTTPAdapter(max_retries=num_retries)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        pool = session.send
        for i in range(num_threats):
            threat_results = []
            with tqdm(total=num_requests, desc=f'Threat {i+1}') as pbar:
                for j in range(num_requests):
                    response = pool(prepared_request)
                    threat_results.append(response)
                    if response.status_code == 200:
                        break
                    time.sleep(pause_before_retry/1000)
                    pbar.update(1)
            results.append(threat_results)
    click.echo(results)


@click.command()
@click.argument('url')
def portscanner(url):
    """
    Performs a TCP port scan on a specified hostname or URL and a range of ports.

    Args:
    - url (str): the hostname or URL of the target host
    """

    # Add a scheme to the URL if it is not present
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url

    # Parse the URL to extract the hostname
    hostname = urlparse(url).hostname or url

    # Resolve the hostname to an IP address
    ip_address = socket.gethostbyname(hostname)

    open_ports = []

    # Define a function to scan a single port
    def scan_port(port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.1)
        try:
            sock.connect((ip_address, port))
            open_ports.append(f"{hostname}:{port}")
        except:
            pass
        finally:
            sock.close()

    # Use multi-threading to scan ports in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(scan_port, port) for port in range(1, 65536)]
        with tqdm(total=len(futures), desc="Scanning Ports", unit="ports") as progress:
            for future in concurrent.futures.as_completed(futures):
                progress.update(1)

    # Print the open ports
    click.echo('\nOpen Ports:')
    for port in open_ports:
        click.echo(port)

@click.command()
@click.argument('base_url')
@click.argument('path', default='../lists/injector')
def injector(base_url, path):
    # Add http or https prefix if missing
    if not base_url.startswith('http'):
        base_url = 'http://' + base_url

    if os.path.isdir(path):
        for filename in os.listdir(path):
            filepath = os.path.join(path, filename)
            if os.path.isfile(filepath):
                with open(filepath) as f:
                    paths = f.read().splitlines()
                    progress_bar = tqdm(paths, desc=filename, position=0, leave=True)
                    for p in progress_bar:
                        url = f"{base_url}/{p}"
                        response = requests.get(url)
                        if response.status_code == 200:
                            click.echo(f"{url} - {response.status_code}")
    elif os.path.isfile(path):
        with open(path) as f:
            paths = f.read().splitlines()
            progress_bar = tqdm(paths, desc=os.path.basename(path), position=0, leave=True)
            for p in progress_bar:
                url = f"{base_url}/{p}"
                response = requests.get(url)
                if response.status_code == 200:
                    click.echo(f"{url} - {response.status_code}")
    else:
        click.echo(f"{path} does not exist")

cli.add_command(linode)
cli.add_command(injector)
cli.add_command(intruder)
cli.add_command(enumerator)
cli.add_command(portscanner)

if __name__ == '__main__':
    cli()