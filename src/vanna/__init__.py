r'''
# Basic Usage

## Getting an API key
```python
import vanna as vn
api_key = vn.get_api_key('my-email@example.com')
vn.set_api_key(api_key)
```

## Setting the dataset
```python
vn.set_dataset('demo-tpc-h')
```

## Asking a question
```python
sql, df, fig, followup_questions = vn.ask(question='What are the top 10 customers by sales?')
```

For a more comprehensive starting guide see the [Starter Notebook](/notebooks/vn-starter/).

# Nomenclature

| Prefix | Definition | Examples |
| --- | --- | --- |
| `vn.set_` | Sets the variable for the current session | [`vn.set_dataset(...)`][vanna.set_dataset] <br> [`vn.set_api_key(...)`][vanna.set_api_key]  |
| `vn.get_` | Performs a read-only operation | [`vn.get_dataset()`][vanna.get_datasets] |
| `vn.add_` | Adds something to the dataset | [`vn.add_sql(...)`][vanna.add_sql] <br> [`vn.add_ddl(...)`][vanna.add_ddl] |
| `vn.generate_` | Generates something using AI based on the information in the dataset | [`vn.generate_sql(...)`][vanna.generate_sql] <br> [`vn.generate_explanation()`][vanna.generate_explanation] |
| `vn.run_` | Runs code (SQL or Plotly) | [`vn.run_sql`][vanna.run_sql] |
| `vn.remove_` | Removes something from the dataset | [`vn.remove_training_data`][vanna.remove_training_data] |
| `vn.update_` | Updates something in the dataset | [`vn.update_dataset_visibility(...)`][vanna.update_dataset_visibility] |
| `vn.connect_` | Connects to a database | [`vn.connect_to_snowflake(...)`][vanna.connect_to_snowflake] |

# API Reference
'''

import requests
import pandas as pd
import json
import dataclasses
import plotly
import psycopg2
import plotly.express as px
import plotly.graph_objects as go
import sqlparse
import logging

from .types import SQLAnswer, Explanation, QuestionSQLPair, Question, QuestionId, DataResult, PlotlyResult, Status, \
    FullQuestionDocument, QuestionList, QuestionCategory, AccuracyStats, UserEmail, UserOTP, ApiKey, OrganizationList, \
    Organization, NewOrganization, StringData, QuestionStringList, Visibility, NewOrganizationMember, DataFrameJSON
from typing import List, Union, Callable, Tuple
from .exceptions import ImproperlyConfigured, DependencyError, ConnectionError, OtpCodeError, SQLRemoveError, \
    ValidationError
from .utils import validate_config_path
import warnings
import traceback
import os

from google.oauth2 import service_account

api_key: Union[str, None] = None  # API key for Vanna.AI

run_sql: Union[Callable[[str], pd.DataFrame], None] = None  # Function to convert SQL to a Pandas DataFrame
"""
**Example**
```python
vn.run_sql = lambda sql: pd.read_sql(sql, engine)
```

Set the SQL to DataFrame function for Vanna.AI. This is used in the [`vn.ask(...)`][vanna.ask] function.
Instead of setting this directly you can also use [`vn.connect_to_snowflake(...)`][vanna.connect_to_snowflake] to set this.

"""

__org: Union[str, None] = None  # Organization name for Vanna.AI

_endpoint = "https://ask.vanna.ai/rpc"
_unauthenticated_endpoint = "https://ask.vanna.ai/unauthenticated_rpc"

logger = logging.getLogger(__name__)


def __unauthenticated_rpc_call(method, params):
    headers = {
        'Content-Type': 'application/json',
    }
    data = {
        "method": method,
        "params": [__dataclass_to_dict(obj) for obj in params]
    }

    response = requests.post(_unauthenticated_endpoint, headers=headers, data=json.dumps(data))
    return response.json()


def __rpc_call(method, params):
    global api_key
    global __org

    if api_key is None:
        raise ImproperlyConfigured("API key not set. Use vn.get_api_key(...) to get an API key.")

    if __org is None and method != "list_orgs":
        raise ImproperlyConfigured("Dataset not set. Use vn.set_dataset(...) to set the dataset to use.")

    if method != "list_orgs":
        headers = {
            'Content-Type': 'application/json',
            'Vanna-Key': api_key,
            'Vanna-Org': __org
        }
    else:
        headers = {
            'Content-Type': 'application/json',
            'Vanna-Key': api_key,
            'Vanna-Org': 'demo-tpc-h'
        }

    data = {
        "method": method,
        "params": [__dataclass_to_dict(obj) for obj in params]
    }

    response = requests.post(_endpoint, headers=headers, data=json.dumps(data))
    return response.json()


def __dataclass_to_dict(obj):
    return dataclasses.asdict(obj)


def get_api_key(email: str, otp_code: Union[str, None] = None) -> str:
    """
    **Example:**
    ```python
    vn.get_api_key(email="my-email@example.com")
    ```

    Login to the Vanna.AI API.

    Args:
        email (str): The email address to login with.
        otp_code (Union[str, None]): The OTP code to login with. If None, an OTP code will be sent to the email address.

    Returns:
        str: The API key.
    """
    vanna_api_key = os.environ.get('VANNA_API_KEY', None)

    if vanna_api_key is not None:
        return vanna_api_key

    if email == 'my-email@example.com':
        raise ValidationError("Please replace 'my-email@example.com' with your email address.")

    if otp_code is None:
        params = [UserEmail(email=email)]

        d = __unauthenticated_rpc_call(method="send_otp", params=params)

        if 'result' not in d:
            raise OtpCodeError("Error sending OTP code.")

        status = Status(**d['result'])

        if not status.success:
            raise OtpCodeError(f"Error sending OTP code: {status.message}")

        otp_code = input("Check your email for the code and enter it here: ")

    params = [UserOTP(email=email, otp=otp_code)]

    d = __unauthenticated_rpc_call(method="verify_otp", params=params)

    if 'result' not in d:
        raise OtpCodeError("Error verifying OTP code.")

    key = ApiKey(**d['result'])

    if key is None:
        raise OtpCodeError("Error verifying OTP code.")

    api_key = key.key

    return api_key


def set_api_key(key: str) -> None:
    """
    Sets the API key for Vanna.AI.

    **Example:**
    ```python
    api_key = vn.get_api_key(email="my-email@example.com")
    vn.set_api_key(api_key)
    ```

    Args:
        key (str): The API key.
    """
    global api_key
    api_key = key

    datasets = get_datasets()

    if len(datasets) == 0:
        raise ConnectionError(
            "There was an error communicating with the Vanna.AI API. Please try again or contact support@vanna.ai")


def get_datasets() -> List[str]:
    """
    **Example:**
    ```python
    datasets = vn.get_datasets()
    ```

    List the datasets that the user is a member of.

    Returns:
        List[str]: A list of dataset names.
    """
    d = __rpc_call(method="list_orgs", params=[])

    if 'result' not in d:
        return []

    orgs = OrganizationList(**d['result'])

    return orgs.organizations


def create_dataset(dataset: str, db_type: str) -> bool:
    """
    **Example:**
    ```python
    vn.create_dataset(dataset="my-dataset", db_type="postgres")
    ```

    Create a new dataset.

    Args:
        dataset (str): The name of the dataset to create.
        db_type (str): The type of database to use for the dataset. This can be "Snowflake", "BigQuery", "Postgres", or anything else.

    Returns:
        bool: True if the dataset was created successfully, False otherwise.
    """
    global __org
    if __org is None:
        __org = 'demo-tpc-h'

    params = [NewOrganization(org_name=dataset, db_type=db_type)]

    d = __rpc_call(method="create_org", params=params)

    if 'result' not in d:
        return False

    status = Status(**d['result'])

    if status.success:
        __org = dataset

    return status.success


def add_user_to_dataset(dataset: str, email: str, is_admin: bool) -> bool:
    """
    **Example:**
    ```python
    vn.add_user_to_dataset(dataset="my-dataset", email="user@example.com")
    ```

    Add a user to an dataset.

    Args:
        dataset (str): The name of the dataset to add the user to.
        email (str): The email address of the user to add.
        is_admin (bool): Whether or not the user should be an admin.

    Returns:
        bool: True if the user was added successfully, False otherwise.
    """

    params = [NewOrganizationMember(org_name=dataset, email=email, is_admin=is_admin)]

    d = __rpc_call(method="add_user_to_org", params=params)

    if 'result' not in d:
        return False

    status = Status(**d['result'])

    if not status.success:
        logger.info(status.message)

    return status.success


def update_dataset_visibility(public: bool) -> bool:
    """
    **Example:**
    ```python
    vn.update_dataset_visibility(public=True)
    ```

    Set the visibility of the current dataset. If a dataset is visible, anyone can see it. If it is not visible, only members of the dataset can see it.

    Args:
        public (bool): Whether or not the dataset should be publicly visible.

    Returns:
        bool: True if the dataset visibility was set successfully, False otherwise.
    """
    params = [Visibility(visibility=public)]

    d = __rpc_call(method="set_org_visibility", params=params)

    if 'result' not in d:
        return False

    status = Status(**d['result'])

    return status.success


def _set_org(org: str) -> None:
    global __org

    my_orgs = get_datasets()
    if org not in my_orgs:
        # Check if org exists
        d = __unauthenticated_rpc_call(method="check_org_exists",
                                       params=[Organization(name=org, user=None, connection=None)])

        if 'result' not in d:
            raise ValidationError("Failed to check if dataset exists")

        status = Status(**d['result'])

        if status.success:
            raise ValidationError(f"An organization with the name {org} already exists")

        create = input(f"Would you like to create dataset '{org}'? (y/n): ")

        if create.lower() == 'y':
            db_type = input("What type of database would you like to use? (Snowflake, BigQuery, Postgres, etc.): ")
            if create_dataset(dataset=org, db_type=db_type):
                __org = org
            else:
                __org = None
                raise ValidationError("Failed to create dataset")
    else:
        __org = org


def set_dataset(dataset: str):
    """
    Set the datasets to use for the Vanna.AI API.

    **Example:**
    ```python
    vn.set_dataset("my-dataset")
    ```

    Args:
        dataset (str): The name of the dataset to use.
    """
    if dataset == 'my-dataset':
        env_dataset = os.environ.get('VANNA_DATASET', None)

        if env_dataset is not None:
            dataset = env_dataset
        else:
            raise ValidationError("Please replace 'my-dataset' with the name of your dataset")

    _set_org(org=dataset)


def add_sql(question: str, sql: str, tag: Union[str, None] = "Manually Trained") -> bool:
    """
    Adds a question and its corresponding SQL query to the dataset's training data

    **Example:**
    ```python
    vn.add_sql(
        question="What is the average salary of employees?",
        sql="SELECT AVG(salary) FROM employees"
    )
    ```

    Args:
        question (str): The question to store.
        sql (str): The SQL query to store.
        tag (Union[str, None]): A tag to associate with the question and SQL query.

    Returns:
        bool: True if the question and SQL query were stored successfully, False otherwise.
    """
    params = [QuestionSQLPair(
        question=question,
        sql=sql,
        tag=tag
    )]

    d = __rpc_call(method="store_sql", params=params)

    if 'result' not in d:
        return False

    status = Status(**d['result'])

    return status.success


def add_ddl(ddl: str) -> bool:
    """
    Adds a DDL statement to the dataset's training data

    **Example:**
    ```python
    vn.add_ddl(
        ddl="CREATE TABLE employees (id INT, name VARCHAR(255), salary INT)"
    )
    ```

    Args:
        ddl (str): The DDL statement to store.

    Returns:
        bool: True if the DDL statement was stored successfully, False otherwise.
    """
    params = [StringData(data=ddl)]

    d = __rpc_call(method="store_ddl", params=params)

    if 'result' not in d:
        return False

    status = Status(**d['result'])

    return status.success


def add_documentation(documentation: str) -> bool:
    """
    Adds documentation to the dataset's training data

    **Example:**
    ```python
    vn.add_documentation(
        documentation="Our organization's definition of sales is the discount price of an item multiplied by the quantity sold."
    )
    ```

    Args:
        documentation (str): The documentation string to store.

    Returns:
        bool: True if the documentation string was stored successfully, False otherwise.
    """
    params = [StringData(data=documentation)]

    d = __rpc_call(method="store_documentation", params=params)

    if 'result' not in d:
        return False

    status = Status(**d['result'])

    return status.success


def train(question: str = None, sql: str = None, ddl: str = None, documentation: bool = False, json_file: str = None,
          sql_file: str = None) -> bool:
    """
    **Example:**
    ```python
    vn.train(
        question="What is the average salary of employees?",
        sql="SELECT AVG(salary) FROM employees"
    )
    ```

    Train Vanna.AI on a question and its corresponding SQL query. This is equivalent to calling [`add_sql()`][vanna.add_sql].

    Args:
        question (str): The question to train on.
        sql (str): The SQL query to train on.
        sql_file (str): The SQL file path.
        json_file (str): The JSON file path.
        ddl (str):  The DDL statement.
        documentation (bool): Generate Documentaion for the SQL.
    """

    if question and not sql:
        example_question = "What is the average salary of employees?"
        raise ValidationError(
            f"Please also provide a SQL query \n Example Question:  {example_question}\n Answer: {ask(question=example_question)}")

    if sql:
        if documentation:
            logger.info("Adding documentation....")
            return add_documentation(sql)
        question = generate_question(sql)
        logger.info("Question generated with sql:", Question, '\nAdding SQL...')
        return add_sql(question=question, sql=sql)

    if ddl:
        logger.info("Adding ddl:", ddl)
        return add_ddl(sql)

    if json_file:
        validate_config_path(json_file)
        with open(json_file, 'r') as js_file:
            data = json.load(js_file)
            logger.info("Adding Questions And SQLs using file:", json_file)
            for question in data:
                add_sql(question=question['question'], sql=question['answer'])

    if sql_file:
        validate_config_path(sql_file)
        with open(sql_file, 'r') as file:
            sql_statements = sqlparse.split(file.read())
            for statement in sql_statements:
                if 'CREATE TABLE' in statement:
                    if add_ddl(statement):
                        logger.info("ddl Added!")
                        return True
                    logger.info("Not able to add DDL")
                    return False
                else:
                    question = generate_question(sql=statement)
                    if add_sql(question=question, sql=statement):
                        logger.info("SQL added!")
                        return True
                    logger.warning("Not able to add sql.")
                    return False


def flag_sql_for_review(question: str, sql: Union[str, None] = None, error_msg: Union[str, None] = None) -> bool:
    """
    **Example:**
    ```python
    vn.flag_sql_for_review(question="What is the average salary of employees?")
    ```
    Flag a question and its corresponding SQL query for review. You can see the tag show up in [`vn.get_all_questions()`][vanna.get_all_questions]

    Args:
        question (str): The question to flag.
        sql (str): The SQL query to flag.
        error_msg (str): The error message to flag.

    Returns:
        bool: True if the question and SQL query were flagged successfully, False otherwise.
    """
    params = [
        QuestionCategory(
            question=question,
            category=QuestionCategory.FLAGGED_FOR_REVIEW,
        )
    ]

    d = __rpc_call(method="set_accuracy_category", params=params)

    if 'result' not in d:
        return False

    status = Status(**d['result'])

    return status.success


# def read_questions_from_github(url: str) -> List[QuestionSQLPair]:
#     """
#     **Example:**
#     ```python
#     url = "https://raw.githubusercontent.com/vanna-ai/vanna-ai/main/data/questions.json"
#     questions = vn.read_questions_from_github(url)
#     ```
#     Read questions and SQL queries from a GitHub URL.

#     Args:
#         url (str): The URL to read from.

#     Returns:
#         List[QuestionSQLPair]: A list of [`QuestionSQLPair`][vanna.QuestionSQLPair] objects.
#     """
#     response = requests.get(url)
#     data = response.json()

#     question_sql_pairs = []
#     for item in data:
#         question = item.get('question')
#         sql = item.get('sql')
#         if question and sql:
#             question_sql_pair = QuestionSQLPair(question=question, sql=sql)
#             question_sql_pairs.append(question_sql_pair)

#     return question_sql_pairs

def remove_sql(question: str) -> bool:
    """
    Remove a question and its corresponding SQL query from the dataset's training data

    **Example:**
    ```python
    vn.remove_sql(question="What is the average salary of employees?")
    ```

    Args:
        question (str): The question to remove.
    """
    params = [Question(question=question)]

    d = __rpc_call(method="remove_sql", params=params)

    if 'result' not in d:
        raise SQLRemoveError(f"Error removing SQL")
        return False

    status = Status(**d['result'])

    if not status.success:
        raise SQLRemoveError(f"Error removing SQL: {status.message}")

    return status.success


def remove_training_data(id: str) -> bool:
    """
    Remove training data from the dataset

    **Example:**
    ```python
    vn.remove_training_data(id="1-ddl")
    ```

    Args:
        id (str): The ID of the training data to remove.
    """
    params = [StringData(data=id)]

    d = __rpc_call(method="remove_training_data", params=params)

    if 'result' not in d:
        raise Exception(f"Error removing training data")
        return False

    status = Status(**d['result'])

    if not status.success:
        raise Exception(f"Error removing training data: {status.message}")

    return status.success

def generate_sql(question: str) -> str:
    """
    **Example:**
    ```python
    vn.generate_sql(question="What is the average salary of employees?")
    # SELECT AVG(salary) FROM employees
    ```

    Generate an SQL query using the Vanna.AI API.

    Args:
        question (str): The question to generate an SQL query for.

    Returns:
        str or None: The SQL query, or None if an error occurred.
    """
    params = [Question(question=question)]

    d = __rpc_call(method="generate_sql_from_question", params=params)

    if 'result' not in d:
        return None

    # Load the result into a dataclass
    sql_answer = SQLAnswer(**d['result'])

    return sql_answer.sql


def generate_followup_questions(question: str, df: pd.DataFrame) -> List[str]:
    """
    **Example:**
    ```python
    vn.generate_followup_questions(question="What is the average salary of employees?", df=df)
    # ['What is the average salary of employees in the Sales department?', 'What is the average salary of employees in the Engineering department?', ...]
    ```

    Generate follow-up questions using the Vanna.AI API.

    Args:
        question (str): The question to generate follow-up questions for.
        df (pd.DataFrame): The DataFrame to generate follow-up questions for.

    Returns:
        List[str] or None: The follow-up questions, or None if an error occurred.
    """
    params = [DataResult(
        question=question,
        sql=None,
        table_markdown=df.head().to_markdown(),
        error=None,
        correction_attempts=0,
    )]

    d = __rpc_call(method="generate_followup_questions", params=params)

    if 'result' not in d:
        return None

    # Load the result into a dataclass
    question_string_list = QuestionStringList(**d['result'])

    return question_string_list.questions


def generate_questions() -> List[str]:
    """
    **Example:**
    ```python
    vn.generate_questions()
    # ['What is the average salary of employees?', 'What is the total salary of employees?', ...]
    ```

    Generate questions using the Vanna.AI API.

    Returns:
        List[str] or None: The questions, or None if an error occurred.
    """
    d = __rpc_call(method="generate_questions", params=[])

    if 'result' not in d:
        return None

    # Load the result into a dataclass
    question_string_list = QuestionStringList(**d['result'])

    return question_string_list.questions


def ask(question: Union[str, None] = None, print_results: bool = True, auto_train: bool = True,
        generate_followups: bool = True) -> Tuple[
    Union[str, None], Union[pd.DataFrame, None], Union[plotly.graph_objs.Figure, None], Union[List[str], None]]:
    """
    **Example:**
    ```python
    # RECOMMENDED IN A NOTEBOOK:
    sql, df, fig, followup_questions = vn.ask()


    sql, df, fig, followup_questions = vn.ask(question="What is the average salary of employees?")
    # SELECT AVG(salary) FROM employees
    ```

    Ask a question using the Vanna.AI API. This generates an SQL query, runs it, and returns the results in a dataframe and a Plotly figure.

    Args:
        question (str): The question to ask. If None, you will be prompted to enter a question.

    Returns:
        str or None: The SQL query, or None if an error occurred.
        pd.DataFrame or None: The results of the SQL query, or None if an error occurred.
        plotly.graph_objs.Figure or None: The Plotly figure, or None if an error occurred.
        List[str] or None: The follow-up questions, or None if an error occurred.
    """

    if question is None:
        question = input("Enter a question: ")

    try:
        sql = generate_sql(question=question)
    except Exception as e:
        logger.info(e)
        return None, None, None, None

    if print_results:
        logger.info(sql)

    if run_sql is None:
        logger.info("If you want to run the SQL query, provide a vn.run_sql function.")
        return sql, None, None, None

    try:
        df = run_sql(sql)

        if print_results:
            try:
                display = __import__('IPython.display', fromlist=['display']).display
                display(df)
            except Exception as e:
                logger.info(df)

        if len(df) > 0 and auto_train:
            add_sql(question=question, sql=sql, tag=types.QuestionCategory.SQL_RAN)

        try:
            plotly_code = generate_plotly_code(question=question, sql=sql, df=df)
            fig = get_plotly_figure(plotly_code=plotly_code, df=df)
            if print_results:
                fig.show()

            if generate_followups:
                followup_questions = generate_followup_questions(question=question, df=df)
                if followup_questions is not None and len(followup_questions) > 0:
                    logger.info("AI-generated follow-up questions:")
                    for followup_question in followup_questions:
                        logger.info(followup_question)

                return sql, df, fig, followup_questions

            return sql, df, fig, None

        except Exception as e:
            # Print stack trace
            traceback.print_exc()
            logger.info("Couldn't run plotly code: ", e)
            return sql, df, None, None

    except Exception as e:
        logger.info("Couldn't run sql: ", e)
        return sql, None, None, None


def generate_plotly_code(question: Union[str, None], sql: Union[str, None], df: pd.DataFrame) -> str:
    """
    **Example:**
    ```python
    vn.generate_plotly_code(
        question="What is the average salary of employees?",
        sql="SELECT AVG(salary) FROM employees",
        df=df
    )
    # fig = px.bar(df, x="name", y="salary")
    ```
    Generate Plotly code using the Vanna.AI API.

    Args:
        question (str): The question to generate Plotly code for.
        sql (str): The SQL query to generate Plotly code for.
        df (pd.DataFrame): The dataframe to generate Plotly code for.

    Returns:
        str or None: The Plotly code, or None if an error occurred.
    """
    params = [DataResult(
        question=question,
        sql=sql,
        table_markdown=df.head().to_markdown(),
        error=None,
        correction_attempts=0,
    )]

    d = __rpc_call(method="generate_plotly_code", params=params)

    if 'result' not in d:
        return None

    # Load the result into a dataclass
    plotly_code = PlotlyResult(**d['result'])

    return plotly_code.plotly_code


def get_plotly_figure(plotly_code: str, df: pd.DataFrame, dark_mode: bool = True) -> plotly.graph_objs.Figure:
    """
    **Example:**
    ```python
    fig = vn.get_plotly_figure(
        plotly_code="fig = px.bar(df, x='name', y='salary')",
        df=df
    )
    fig.show()
    ```
    Get a Plotly figure from a dataframe and Plotly code.

    Args:
        df (pd.DataFrame): The dataframe to use.
        plotly_code (str): The Plotly code to use.

    Returns:
        plotly.graph_objs.Figure: The Plotly figure.
    """
    ldict = {'df': df, 'px': px, 'go': go}
    exec(plotly_code, globals(), ldict)

    fig = ldict.get('fig', None)

    if fig is None:
        return None

    if dark_mode:
        fig.update_layout(template="plotly_dark")

    return fig


def get_results(cs, default_database: str, sql: str) -> pd.DataFrame:
    """
    DEPRECATED. Use `vn.run_sql` instead.
    Run the SQL query and return the results as a pandas dataframe. This is just a helper function that does not use the Vanna.AI API.

    Args:
        cs: Snowflake connection cursor.
        default_database (str): The default database to use.
        sql (str): The SQL query to execute.

    Returns:
        pd.DataFrame: The results of the SQL query.
    """
    logger.info("`vn.get_results()` is deprecated. Use `vn.run_sql()` instead.")
    warnings.warn("`vn.get_results()` is deprecated. Use `vn.run_sql()` instead.")

    cs.execute(f"USE DATABASE {default_database}")

    cur = cs.execute(sql)

    results = cur.fetchall()

    # Create a pandas dataframe from the results
    df = pd.DataFrame(results, columns=[desc[0] for desc in cur.description])

    return df


def generate_explanation(sql: str) -> str:
    """

    **Example:**
    ```python
    vn.generate_explanation(sql="SELECT * FROM students WHERE name = 'John Doe'")
    # 'This query selects all columns from the students table where the name is John Doe.'
    ```
    
    Generate an explanation of an SQL query using the Vanna.AI API.

    Args:
        sql (str): The SQL query to generate an explanation for.
    
    Returns:
        str or None: The explanation, or None if an error occurred.

    """
    params = [SQLAnswer(
        raw_answer="",
        prefix="",
        postfix="",
        sql=sql,
    )]

    d = __rpc_call(method="generate_explanation", params=params)

    if 'result' not in d:
        return None

    # Load the result into a dataclass
    explanation = Explanation(**d['result'])

    return explanation.explanation


def generate_question(sql: str) -> str:
    """

    **Example:**
    ```python
    vn.generate_question(sql="SELECT * FROM students WHERE name = 'John Doe'")
    # 'What is the name of the student?'
    ```
    
    Generate a question from an SQL query using the Vanna.AI API.

    Args:
        sql (str): The SQL query to generate a question for.
    
    Returns:
        str or None: The question, or None if an error occurred.

    """
    params = [SQLAnswer(
        raw_answer="",
        prefix="",
        postfix="",
        sql=sql,
    )]

    d = __rpc_call(method="generate_question", params=params)

    if 'result' not in d:
        return None

    # Load the result into a dataclass
    question = Question(**d['result'])

    return question.question


def get_all_questions() -> pd.DataFrame:
    """
    Get a list of questions from the Vanna.AI API.

    **Example:**
    ```python
    questions = vn.get_all_questions()
    ```

    Returns:
        pd.DataFrame or None: The list of questions, or None if an error occurred.

    """
    # params = [Question(question="")]
    params = []

    d = __rpc_call(method="get_all_questions", params=params)

    if 'result' not in d:
        return None

    # Load the result into a dataclass
    all_questions = DataFrameJSON(**d['result'])

    df = pd.read_json(all_questions.data)

    return df

def get_training_data() -> pd.DataFrame:
    """
    Get the training data for the current dataset

    **Example:**
    ```python
    training_data = vn.get_training_data()
    ```

    Returns:
        pd.DataFrame or None: The training data, or None if an error occurred.

    """
    # params = [Question(question="")]
    params = []

    d = __rpc_call(method="get_training_data", params=params)

    if 'result' not in d:
        return None

    # Load the result into a dataclass
    training_data = DataFrameJSON(**d['result'])

    df = pd.read_json(training_data.data)

    return df

def connect_to_snowflake(account: str, username: str, password: str, database: str, role: Union[str, None] = None):
    """
    Connect to Snowflake using the Snowflake connector. This is just a helper function to set [`vn.run_sql`][vanna.run_sql]

    **Example:**
    ```python
    import snowflake.connector

    vn.connect_to_snowflake(
        account="myaccount",
        username="myusername",
        password="mypassword",
        database="mydatabase",
        role="myrole",
    )
    ```

    Args:
        account (str): The Snowflake account name.
        username (str): The Snowflake username.
        password (str): The Snowflake password.
        database (str): The default database to use.
        role (Union[str, None], optional): The role to use. Defaults to None.
    """

    try:
        import snowflake.connector as snowflake
    except ImportError:
        raise DependencyError("You need to install required dependencies to execute this method, run command:"
                                  " \npip install vanna[snowflake]")

    if username == 'my-username':
        username_env = os.getenv('SNOWFLAKE_USERNAME')

        if username_env is not None:
            username = username_env
        else:
            raise ImproperlyConfigured("Please set your Snowflake username.")

    if password == 'my-password':
        password_env = os.getenv('SNOWFLAKE_PASSWORD')

        if password_env is not None:
            password = password_env
        else:
            raise ImproperlyConfigured("Please set your Snowflake password.")

    if account == 'my-account':
        account_env = os.getenv('SNOWFLAKE_ACCOUNT')

        if account_env is not None:
            account = account_env
        else:
            raise ImproperlyConfigured("Please set your Snowflake account.")

    if database == 'my-database':
        database_env = os.getenv('SNOWFLAKE_DATABASE')

        if database_env is not None:
            database = database_env
        else:
            raise ImproperlyConfigured("Please set your Snowflake database.")

    conn = snowflake.connector.connect(
        user=username,
        password=password,
        account=account,
        database=database,
    )

    def run_sql_snowflake(sql: str) -> pd.DataFrame:
        cs = conn.cursor()

        if role is not None:
            cs.execute(f"USE ROLE {role}")
        cs.execute(f"USE DATABASE {database}")

        cur = cs.execute(sql)

        results = cur.fetchall()

        # Create a pandas dataframe from the results
        df = pd.DataFrame(results, columns=[desc[0] for desc in cur.description])

        return df

    global run_sql
    run_sql = run_sql_snowflake


def connect_to_bigquery(cred_file_path: str, project_id: str = None):
    """
    Connect to gcs using the bigquery connector. This is just a helper function to set [`vn.run_sql`][vanna.run_sql]

    **Example:**
    ```python
    import bigquery.Client

    vn.connect_to_bigquery(
        project_id="myprojectid",
        cred_file_path="path/to/credentials.json",
    )
    ```

    Args:
        project_id (str): The gcs project id.
        cred_file_path: The gcs credential file path
    """

    try:
        from google.api_core.exceptions import GoogleAPIError
        from google.cloud import bigquery
    except ImportError:
        raise DependencyError("You need to install required dependencies to execute this method, run command:"
                                  " \npip install vanna[bigquery]")

    if not project_id:
        project_id = os.getenv('PROJECT_ID')

    if not project_id:
        raise ImproperlyConfigured("Please set your Google Cloud Project ID.")

    # Validate file path and pemissions
    validate_config_path(cred_file_path)

    with open(cred_file_path, 'r') as f:
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(f.read()),
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

    conn = None

    try:
        conn = bigquery.Client(project=project_id, credentials=credentials)
    except:
        raise ImproperlyConfigured("Could not connect to bigquery please correct credentials")

    def run_sql_bigquery(sql: str) -> Union[pd.DataFrame, None]:
        if conn:
            try:
                job = conn.query(sql)
                df = job.result().to_dataframe()
                return df
            except GoogleAPIError as error:
                errors = []
                for error in error.errors:
                    errors.append(error["message"])
                raise errors
        return None

    global run_sql
    run_sql = run_sql_bigquery


def connect_to_postgres(host: str = None, dbname: str = None, user: str = None, password: str = None, port: int = None):
    """
    Connect to postgres using the psycopg2 connector. This is just a helper function to set [`vn.run_sql`][vanna.run_sql]

    **Example:**
    ```python
    import psycopg2.connect

    vn.connect_to_bigquery(
        host="myhost",
        dbname="mydatabase",
        user="myuser",
        password="mypassword",
        port=5432
    )
    ```

    Args:
        host (str): The postgres host.
        dbname (str): The postgres database name.
        user (str): The postgres user.
        password (str): The postgres password.
        port (int): The postgres Port.

    """

    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        raise DependencyError("You need to install required dependencies to execute this method,"
                                  " run command: \npip install vanna[postgres]")

    if not host:
        host = os.getenv('HOST')

    if not host:
        raise ImproperlyConfigured("Please set your Postgres Host")

    if not dbname:
        dbname = os.getenv('DATABASE')

    if not dbname:
        raise ImproperlyConfigured("Please set your Postgres Database")

    if not user:
        user = os.getenv('USER')

    if not user:
        raise ImproperlyConfigured("Please set your Postgres User")

    if not password:
        password = os.getenv('PASSWORD')

    if not password:
        raise ImproperlyConfigured("Please set your Postgres Password")

    if not port:
        port = os.getenv('PORT')

    if not port:
        raise ImproperlyConfigured("Please set your Postgres Port")

    conn = None

    try:
        conn = psycopg2.connect(
            host=host,
            dbname=dbname,
            user=user,
            password=password,
            port=port,
        )
    except psycopg2.Error as e:
        raise ValidationError(e)

    def run_sql_postgres(sql: str) -> Union[pd.DataFrame, None]:
        if conn:
            try:
                cs = conn.cursor()
                cs.execute(sql)
                results = cs.fetchall()

                # Create a pandas dataframe from the results
                df = pd.DataFrame(results, columns=[desc[0] for desc in cs.description])
                return df

            except psycopg2.Error as e:
                raise ValidationError(e)

    global run_sql
    run_sql = run_sql_postgres
